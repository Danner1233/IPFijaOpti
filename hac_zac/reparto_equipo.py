# -*- coding: utf-8 -*-
"""Reparto del ADMIN entre los PEM (la misma regla de la autoasignacion), sin servidor.

* Recibe solo quien el admin tiene ACTIVO y ademas esta ACTIVO en la app (pestana Equipo: la uso en los ultimos
  5 min o tiene un proceso corriendo).
* Una solicitud a la vez: no recibe si tiene alguna en SharePoint a su nombre sin estado final (de las ultimas 24 h).
* Turno: el que lleva mas tiempo sin recibir. Se reparte la libre mas antigua.
* No se le devuelve una solicitud a quien la libero (queda la nota "libero la solicitud" en Observaciones).

La lista de PEM se publica en <carpeta del equipo>/reparto.json: mientras el admin este repartiendo (archivo
actualizado hace menos de 10 min), los PEM de la lista NO se autoasignan. Si el admin se detiene, vuelven a hacerlo.
"""
import json
import os
import re
from datetime import datetime, timedelta

from . import cola

VIGENTE_MIN = 10            # si el admin no publica en este tiempo, los PEM vuelven a autoasignarse
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


def elegibles(roster, presencia_por_nombre, ocup):
    """PEM activos por el admin, Activos en la app y libres; primero el que lleva mas tiempo sin recibir."""
    cand = [p for p in roster if p.get("activo") and p["nombre"] not in ocup and
            presencia_por_nombre.get(_plano(p["nombre"])) == "en_linea"]
    return sorted(cand, key=lambda p: p.get("ultimo") or "")


def plan(items, roster, presencia_por_nombre, ahora=None):
    """[(item, nombre)] a asignar ahora."""
    ocup = ocupados(items, roster, ahora)
    cand = elegibles(roster, presencia_por_nombre, ocup)
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


def publicar(carpeta_equipo, roster, admin, ahora=None):
    """El admin avisa al equipo que esta repartiendo y a quienes (cada vuelta de su lector)."""
    if not carpeta_equipo:
        return
    ahora = ahora or datetime.now()
    datos = {"admin": admin, "actualizado": ahora.isoformat(timespec="seconds"),
             "pems": [{"nombre": p["nombre"], "activo": bool(p.get("activo"))} for p in roster]}
    os.makedirs(carpeta_equipo, exist_ok=True)
    tmp = ruta_reparto(carpeta_equipo) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta_reparto(carpeta_equipo))


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
    return ("detenido" if minutos >= VIGENTE_MIN else "ok"), minutos, faltan


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
