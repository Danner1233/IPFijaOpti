# -*- coding: utf-8 -*-
"""Quien esta en linea en el equipo, sin servidor: cada aplicacion deja su estado en una carpeta compartida
(OneDrive / SharePoint sincronizada en todos los PC) y lee la de los demas.

* ACTIVO   : uso la aplicacion (clic, tecla o rueda) en los ultimos 5 minutos, o tiene un proceso corriendo.
* AUSENTE  : la aplicacion esta abierta pero lleva 5 minutos sin uso.
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


def publicar(carpeta_equipo, nombre, ultima_actividad, ocupado, ahora=None):
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
        if not act or (ahora - act).total_seconds() > DESCONECTADO_S:
            estado = "desconectado"
        hoy = r.get("fecha") == ahora.date().isoformat()
        out.append({"nombre": r["nombre"], "estado": estado, "ultima_actividad": r.get("ultima_actividad") or "",
                    "actualizado": r.get("actualizado") or "",
                    "en_linea_hoy_min": int((r.get("en_linea_hoy_s") or 0) / 60) if hoy else 0})
    orden = {"en_linea": 0, "ausente": 1, "desconectado": 2}
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


ETIQUETA = {"en_linea": "● Activo", "ausente": "◐ Ausente", "desconectado": "○ Desconectado"}
