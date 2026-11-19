# -*- coding: utf-8 -*-
"""Reparto del ADMIN entre los PEM (la misma regla de la autoasignacion), sin servidor.

* Recibe solo quien el admin tiene ACTIVO y ademas esta ACTIVO en la app (pestana Equipo: la uso en los ultimos
  5 min o tiene un proceso corriendo).
* Una solicitud a la vez: no recibe si tiene alguna en SharePoint a su nombre sin estado final (de las ultimas 24 h).
* Turno: el que lleva mas tiempo sin recibir. Se reparte la libre mas antigua.
* No se le devuelve una solicitud a quien la libero (queda la nota "libero la solicitud" en Observaciones).

* Turnos: solo recibe quien esta EN TURNO (turnos.py: franja de la semana; corte 30 min antes de salir).

Archivos en <carpeta del equipo>:
* roster.json  : la lista de PEM (activo, franja, ultimo) COMPARTIDA entre los admin (asi cualquiera puede repartir).
* reparto.json : quien esta repartiendo y cuando fue su ultima vuelta (+ la lista publicada).
Varios admin: reparte UNO (el de la vuelta mas reciente); si lleva LIDER_S sin repartir, otro admin conectado lo toma
solo. Si NINGUN admin reparte en RESPALDO_MIN, los PEM en turno se autoasignan una a la vez (si el admin lo permite).
SharePoint evita las dobles en todos los casos (se escribe solo si PEM_ASIGNADO sigue vacio, con control de ETag).
"""
import json
import os
import re
from datetime import datetime, timedelta

from . import cola, turnos

VIGENTE_MIN = 10            # (compatibilidad) lista publicada vigente
LIDER_S = 90                # si el admin que reparte no da una vuelta en 90 s, otro admin toma el reparto
RESPALDO_MIN = 5            # si ningun admin reparte en 5 min, los PEM en turno se autoasignan (si se permite)
MAX_HORAS = 24              # solicitudes abiertas mas viejas que esto no bloquean a nadie
NOTA_LIBERO = "libero la solicitud"


def _plano(t):
    return cola._plano(t)


def mismo(a, b):
    return bool(_plano(a)) and _plano(a) == _plano(b)


# ---------------------------------------------------------------------------------------------- reglas
def ocupados(items, roster, ahora=None):
    """Nombres (del roster) que tienen una solicitud abierta en SharePoint."""
    ahora = ahora or datetime.now()
    out = set()
    for it in items:
        d = cola.desde_sp(it)
        if not str(d.get("pem") or "").strip():
            continue
        creada = cola._a_local(d.get("creada"))
        if creada and (ahora - creada).total_seconds() > MAX_HORAS * 3600:
            continue
        for p in roster:
            if cola.es_mia(d, p["nombre"]):           # es_mia ya excluye Exitosa / No exitosa / Escalamiento
                out.add(p["nombre"])
    return out


def liberadores(item):
    """Planos de los nombres que liberaron esta solicitud (por la nota en Observaciones)."""
    obs = _plano(re.sub(r"<[^>]+>", " ", str(item.get("Observaciones") or "")))
    return set(m.strip() for m in re.findall(r"pem ([^:\]\[]+?): " + NOTA_LIBERO, obs))


def elegibles(roster, presencia_por_nombre, ocup, ahora=None):
    """PEM activos por el admin, EN TURNO, Activos en la app y libres; primero el que lleva mas tiempo sin recibir."""
    cand = [p for p in roster if p.get("activo") and p["nombre"] not in ocup and
            turnos.puede_recibir(p.get("franja"), ahora) and
            presencia_por_nombre.get(_plano(p["nombre"])) == "en_linea"]
    return sorted(cand, key=lambda p: p.get("ultimo") or "")


def plan(items, roster, presencia_por_nombre, ahora=None):
    """[(item, nombre)] a asignar ahora."""
    ocup = ocupados(items, roster, ahora)
    cand = elegibles(roster, presencia_por_nombre, ocup, ahora)
    libres = sorted((it for it in items if cola.es_libre(it)), key=lambda i: str(i.get("Created") or ""))
    out = []
    for it in libres:
        no = liberadores(it)
        p = next((c for c in cand if _plano(c["nombre"]) not in no), None)
        if p is None:
            continue
        out.append((it, p["nombre"]))
        cand.remove(p)
    return out


def presencia_por_nombre(carpeta_equipo, ahora=None):
    """{nombre plano: 'en_linea'|'ausente'|'desconectado'} desde la carpeta del equipo."""
    from . import presencia
    if not carpeta_equipo:
        return {}
    return {_plano(r["nombre"]): r["estado"] for r in presencia.equipo(carpeta_equipo, ahora)}


# ---------------------------------------------------------------------------------------------- reparto.json
def ruta_reparto(carpeta_equipo):
    return os.path.join(carpeta_equipo, "reparto.json")


def _escribir_json(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)


def publicar(carpeta_equipo, roster, admin, ahora=None, respaldo=True):
    """El admin avisa al equipo que esta repartiendo, a quienes y con que franja (cada vuelta de su lector)."""
    if not carpeta_equipo:
        return
    ahora = ahora or datetime.now()
    datos = {"admin": admin, "actualizado": ahora.isoformat(timespec="seconds"), "respaldo": bool(respaldo),
             "pems": [{"nombre": p["nombre"], "activo": bool(p.get("activo")), "franja": p.get("franja") or ""}
                      for p in roster]}
    _escribir_json(ruta_reparto(carpeta_equipo), datos)


# ---------------------------------------------------------------------------------------------- roster compartido
def ruta_roster(carpeta_equipo):
    return os.path.join(carpeta_equipo, "roster.json")


def roster(carpeta_equipo=""):
    """La lista de PEM. Con carpeta del equipo es la COMPARTIDA (roster.json); la primera vez se crea con la lista
    local de este PC. Sin carpeta, la local (ingenieros.json)."""
    local = cola.ingenieros()
    if not carpeta_equipo:
        return local
    try:
        with open(ruta_roster(carpeta_equipo), encoding="utf-8") as f:
            lista = json.load(f).get("pems")
        if isinstance(lista, list):
            return lista
    except FileNotFoundError:
        if local:
            try:
                guardar_roster(carpeta_equipo, local)
            except OSError:
                pass
        return local
    except (OSError, ValueError, AttributeError):
        pass
    return local


def guardar_roster(carpeta_equipo, lista):
    cola.guardar_ingenieros(lista)                      # copia local (por si la carpeta no esta)
    if carpeta_equipo:
        _escribir_json(ruta_roster(carpeta_equipo), {"actualizado": datetime.now().isoformat(timespec="seconds"),
                                                     "pems": lista})


def _cambiar(carpeta_equipo, nombre, **campos):
    lista = roster(carpeta_equipo)
    for p in lista:
        if p["nombre"] == nombre:
            p.update(campos)
    guardar_roster(carpeta_equipo, lista)


def agregar(carpeta_equipo, nombre):
    nombre = " ".join(str(nombre).split())
    lista = roster(carpeta_equipo)
    if nombre and not any(mismo(p["nombre"], nombre) for p in lista):
        lista.append({"nombre": nombre, "activo": False, "whatsapp": "", "ultimo": "", "franja": ""})
        guardar_roster(carpeta_equipo, lista)


def quitar(carpeta_equipo, nombre):
    guardar_roster(carpeta_equipo, [p for p in roster(carpeta_equipo) if p["nombre"] != nombre])


def poner_activo(carpeta_equipo, nombre, activo):
    _cambiar(carpeta_equipo, nombre, activo=bool(activo))


def poner_franja(carpeta_equipo, nombre, franja):
    _cambiar(carpeta_equipo, nombre, franja=turnos.franja_valida(franja))


def franja_de(carpeta_equipo, nombre):
    """Franja de un PEM segun la lista compartida (o la ultima publicada)."""
    for p in roster(carpeta_equipo) or leer(carpeta_equipo).get("pems") or []:
        if mismo(p.get("nombre"), nombre):
            return p.get("franja") or ""
    return ""


# ---------------------------------------------------------------------------------------------- quien reparte
def _hace_s(d, ahora):
    try:
        return ((ahora or datetime.now()) - datetime.fromisoformat(d.get("actualizado", ""))).total_seconds()
    except (ValueError, TypeError):
        return None


def quien_reparte(carpeta_equipo, ahora=None):
    """(admin, segundos desde su ultima vuelta) o ("", None)."""
    d = leer(carpeta_equipo) if carpeta_equipo else {}
    return d.get("admin") or "", _hace_s(d, ahora)


def debo_repartir(carpeta_equipo, yo, ahora=None):
    """Entre varios admin reparte uno: yo si soy el ultimo que reparte o si el otro lleva LIDER_S sin dar vueltas."""
    admin, s = quien_reparte(carpeta_equipo, ahora)
    return not admin or s is None or mismo(admin, yo) or s > LIDER_S


def respaldo_activo(carpeta_equipo, nombre, ahora=None):
    """True si este PEM debe autoasignarse como RESPALDO: ningun admin reparte hace RESPALDO_MIN, el admin dejo el
    respaldo permitido, y el PEM esta activo en la lista y en turno."""
    if not carpeta_equipo or not nombre:
        return False
    d = leer(carpeta_equipo)
    s = _hace_s(d, ahora)
    if s is not None and s < RESPALDO_MIN * 60:
        return False                                   # un admin esta repartiendo
    if d and not d.get("respaldo", True):
        return False
    p = next((x for x in roster(carpeta_equipo) or d.get("pems") or [] if mismo(x.get("nombre"), nombre)), None)
    return bool(p and p.get("activo") and turnos.puede_recibir(p.get("franja"), ahora))


def leer(carpeta_equipo):
    try:
        with open(ruta_reparto(carpeta_equipo), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return {}


def lo_reparte_el_admin(carpeta_equipo, nombre, ahora=None):
    """True si el admin esta repartiendo (publico hace < VIGENTE_MIN) y `nombre` esta en su lista:
    ese PEM NO debe autoasignarse."""
    if not carpeta_equipo or not nombre:
        return False
    d = leer(carpeta_equipo)
    try:
        t = datetime.fromisoformat(d.get("actualizado", ""))
    except ValueError:
        return False
    if (ahora or datetime.now()) - t > timedelta(minutes=VIGENTE_MIN):
        return False
    return any(mismo(p.get("nombre"), nombre) for p in d.get("pems") or [])


def estado_publicacion(carpeta_equipo, roster, ahora=None):
    """Para el admin: ¿su lector esta publicando el reparto? Devuelve (codigo, minutos, faltan):
    "sin_archivo" (nunca publico), "detenido" (hace >= VIGENTE_MIN: los PEM se autoasignan), "ok".
    `faltan` = PEM de la lista que aun no salen en lo publicado (los toma en la proxima vuelta)."""
    d = leer(carpeta_equipo) if carpeta_equipo else {}
    try:
        t = datetime.fromisoformat(d.get("actualizado", ""))
    except (ValueError, TypeError):
        return "sin_archivo", None, []
    minutos = max(0, int(((ahora or datetime.now()) - t).total_seconds() // 60))
    publicados = {_plano(p.get("nombre")) for p in d.get("pems") or []}
    faltan = [p["nombre"] for p in roster if _plano(p["nombre"]) not in publicados]
    return ("detenido" if minutos >= RESPALDO_MIN else "ok"), minutos, faltan


# ---------------------------------------------------------------------------------------------- PIN admin
def hash_pin(pin, sal=None):
    import hashlib
    import secrets
    sal = sal or secrets.token_hex(8)
    return sal + "$" + hashlib.sha256((sal + str(pin)).encode("utf-8")).hexdigest()


# PIN del rol administrador (el mismo para todos los admin). Se guarda solo su huella, no el numero.
PIN_ADMIN = "9f3a1c7e5b2d4086$b42c88380e906ec1a58cafab74fb2b2b88e846e6977305ca212979c0fe6ab03f"


def pin_admin_valido(pin):
    return pin_valido(str(pin or "").strip(), PIN_ADMIN)


def pin_valido(pin, guardado):
    import hmac
    if not guardado or "$" not in guardado:
        return False
    sal = guardado.split("$", 1)[0]
    return hmac.compare_digest(hash_pin(pin, sal), guardado)
