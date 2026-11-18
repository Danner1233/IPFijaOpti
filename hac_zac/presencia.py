# -*- coding: utf-8 -*-
"""Quien esta en linea en el equipo, sin servidor: cada aplicacion deja su estado en una carpeta compartida
(OneDrive / SharePoint sincronizada en todos los PC) y lee la de los demas.

* ACTIVO   : uso la aplicacion (clic, tecla o rueda) en los ultimos 5 minutos, o tiene un proceso corriendo.
* AUSENTE  : la aplicacion esta abierta pero lleva 5 minutos sin uso.
* EN PAUSA : el mismo PEM se puso en pausa (razon opcional y tiempo); vuelve solo al cumplirse.
* DESCONECTADO: su archivo no se actualiza hace mas de 3 minutos (aplicacion cerrada, PC apagado o sin red).

Tambien se suman los minutos EN LINEA del dia (para medir tiempo).
Archivo por persona: <carpeta_equipo>/presencia/<Nombre>.json  (sin datos de clientes).
"""
import json
import os
import re
import socket
from datetime import datetime

AUSENTE_S = 5 * 60          # 5 minutos sin usar la app
DESCONECTADO_S = 3 * 60     # archivo sin actualizar (la app escribe cada 60 s; OneDrive puede tardar)
TICK_MAX_S = 120            # si el PC durmio, no se suman horas de golpe


def _iso(d):
    return d.isoformat(timespec="seconds")


def _dt(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def carpeta(carpeta_equipo):
    return os.path.join(carpeta_equipo, "presencia")


def archivo(carpeta_equipo, nombre):
    seguro = re.sub(r"[^A-Za-z0-9_\- ]", "_", " ".join(str(nombre).split())).strip() or "sin_nombre"
    return os.path.join(carpeta(carpeta_equipo), seguro + ".json")


def estado_propio(ultima_actividad, ocupado, ahora):
    if ocupado or (ultima_actividad and (ahora - ultima_actividad).total_seconds() < AUSENTE_S):
        return "en_linea"
    return "ausente"


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------------------------- pausa
# El PEM se pone EN PAUSA (almuerzo, reunion...) con razon opcional y un tiempo: no se le reparte ni se autoasigna.
# Al cumplirse el tiempo vuelve solo a recibir. Se guarda en los datos locales (pausa.json) y se publica al equipo.
MOTIVOS_PAUSA = ("Almuerzo", "Pausa activa", "Reunión", "Capacitación", "Baño")
MINUTOS_PAUSA = (15, 30, 60, 90)


def pausa_vigente(pausa, ahora=None):
    """{'hasta','razon','desde'} si la pausa sigue corriendo, si no None."""
    if not isinstance(pausa, dict):
        return None
    hasta = _dt(pausa.get("hasta"))
    if not hasta or (ahora or datetime.now()) >= hasta:
        return None
    return pausa


def mi_pausa(ahora=None):
    from . import cola
    return pausa_vigente(cola._leer("pausa.json", {}), ahora)


def poner_pausa(minutos, razon="", ahora=None, carpeta_equipo="", nombre=""):
    from datetime import timedelta
    from . import cola
    ahora = ahora or datetime.now()
    cerrar_pausa_vencida(carpeta_equipo, nombre, ahora)          # una anterior que vencio con la app cerrada
    p = {"desde": _iso(ahora), "hasta": _iso(ahora + timedelta(minutes=int(minutos))),
         "razon": " ".join(str(razon or "").split())[:80]}
    cola._escribir("pausa.json", p)
    return p


def quitar_pausa(carpeta_equipo="", nombre="", ahora=None):
    """El PEM pulso Reanudar: queda en el reporte de pausas (si ya habia vencido, como 'Se cumplio el tiempo')."""
    from . import cola, reportes
    ahora = ahora or datetime.now()
    p = cola._leer("pausa.json", {})
    if p.get("desde"):
        hasta = _dt(p.get("hasta"))
        vencida = hasta and ahora >= hasta
        reportes.registrar_pausa(carpeta_equipo, nombre, p, hasta if vencida else ahora,
                                 reportes.SE_CUMPLIO if vencida else reportes.REANUDO)
    cola._escribir("pausa.json", {})


def cerrar_pausa_vencida(carpeta_equipo, nombre, ahora=None):
    """Si la pausa ya se cumplio, la registra en el reporte y la borra. True si cerro una."""
    from . import cola
    ahora = ahora or datetime.now()
    with cola._bloqueo():                                # dos ventanas en el mismo PC: una sola fila
        p = cola._leer("pausa.json", {})
        if not p.get("desde") or pausa_vigente(p, ahora):
            return False
        quitar_pausa(carpeta_equipo, nombre, ahora)
        return True


def texto_pausa(pausa):
    """'⏸ En pausa: Almuerzo (hasta 13:30)'."""
    h = _dt(pausa.get("hasta"))
    hasta = " (hasta %s)" % h.strftime("%H:%M") if h else ""
    return ETIQUETA["pausa"] + (": " + pausa["razon"] if pausa.get("razon") else "") + hasta


def publicar(carpeta_equipo, nombre, ultima_actividad, ocupado, ahora=None, pausa=None, caso=""):
    """Escribe mi estado y suma mis minutos en linea de hoy. Devuelve el registro escrito.
    Si hay dos ventanas abiertas en este PC (script y centro de control), se toma la actividad mas reciente y el
    tiempo no se cuenta doble (se suma desde el ultimo 'tick' guardado, no por ventana)."""
    ahora = ahora or datetime.now()
    ruta = archivo(carpeta_equipo, nombre)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    previo = _leer(ruta)
    pc = socket.gethostname()
    hoy = ahora.date().isoformat()
    if previo.get("pc") == pc:
        otra = _dt(previo.get("ultima_actividad"))
        if otra and (not ultima_actividad or otra > ultima_actividad):
            ultima_actividad = otra
    estado = estado_propio(ultima_actividad, ocupado, ahora)
    segundos = float(previo.get("en_linea_hoy_s") or 0) if previo.get("fecha") == hoy else 0.0
    tick = _dt(previo.get("tick"))
    if previo.get("estado") == "en_linea" and tick and tick.date() == ahora.date():
        segundos += min(max(0.0, (ahora - tick).total_seconds()), TICK_MAX_S)
    reg = {"nombre": " ".join(str(nombre).split()), "estado": estado, "pc": pc, "fecha": hoy,
           "ultima_actividad": _iso(ultima_actividad) if ultima_actividad else "",
           "tick": _iso(ahora), "actualizado": _iso(ahora), "en_linea_hoy_s": int(segundos)}
    if caso:
        reg["caso"] = str(caso)                 # solicitud en proceso (para que el equipo vea quien trabaja)
    pausa = pausa_vigente(pausa, ahora)
    if pausa:
        reg["pausa"] = {"hasta": pausa.get("hasta", ""), "razon": pausa.get("razon", "")}
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)
    return reg


def equipo(carpeta_equipo, ahora=None):
    """Lista de {'nombre','estado','ultima_actividad','en_linea_hoy_min','actualizado'} ordenada:
    en linea, ausentes, desconectados."""
    ahora = ahora or datetime.now()
    out = []
    try:
        nombres = [n for n in os.listdir(carpeta(carpeta_equipo)) if n.endswith(".json")]
    except OSError:
        return out
    for n in nombres:
        r = _leer(os.path.join(carpeta(carpeta_equipo), n))
        if not r.get("nombre"):
            continue
        act = _dt(r.get("actualizado"))
        estado = r.get("estado") or "ausente"
        pausa = None
        if not act or (ahora - act).total_seconds() > DESCONECTADO_S:
            estado = "desconectado"
        else:
            pausa = pausa_vigente(r.get("pausa"), ahora)
            if pausa:
                estado = "pausa"            # abierta pero en pausa: no se le reparte
        hoy = r.get("fecha") == ahora.date().isoformat()
        out.append({"nombre": r["nombre"], "estado": estado, "ultima_actividad": r.get("ultima_actividad") or "",
                    "actualizado": r.get("actualizado") or "",
                    "en_linea_hoy_min": int((r.get("en_linea_hoy_s") or 0) / 60) if hoy else 0,
                    "pausa": pausa, "caso": r.get("caso") or ""})
    orden = {"en_linea": 0, "pausa": 1, "ausente": 2, "desconectado": 3}
    return sorted(out, key=lambda x: (orden.get(x["estado"], 3), x["nombre"].lower()))


def hace(iso, ahora=None):
    """'hace 3 min' / 'hace 2 h' / '—'."""
    d = _dt(iso)
    if not d:
        return "—"
    s = int(((ahora or datetime.now()) - d).total_seconds())
    if s < 60:
        return "hace un momento"
    if s < 3600:
        return "hace %d min" % (s // 60)
    if s < 86400:
        return "hace %d h" % (s // 3600)
    return d.strftime("%d/%m %H:%M")


ETIQUETA = {"en_linea": "● Activo", "ausente": "◐ Ausente", "desconectado": "○ Desconectado", "pausa": "⏸ En pausa"}


def situacion(estado, caso="", pausa=None):
    """Lo que se muestra del PEM en Equipo/Admin: (clave, texto).
    en_proceso / disponible (activo con o sin solicitud), pausa, ausente, desconectado."""
    if estado == "desconectado":
        return "desconectado", ETIQUETA["desconectado"]
    if estado == "pausa" or pausa:
        return "pausa", texto_pausa(pausa or {})
    if estado == "ausente":
        return "ausente", ETIQUETA["ausente"] + (" · con la %s" % caso if caso else "")
    if caso:
        return "en_proceso", "● En proceso · %s" % caso
    return "disponible", "● Disponible"
