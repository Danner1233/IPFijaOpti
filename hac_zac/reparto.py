# -*- coding: utf-8 -*-
"""Reparto central de solicitudes entre los PEM (logica pura: sin SharePoint, sin red, sin archivos).

Reglas (las mismas de admin_agente.py, ahora con disponibilidad en vivo):
* Solo recibe un PEM que tiene la aplicacion ABIERTA (latido reciente) y se marco DISPONIBLE.
* Una solicitud a la vez: no recibe si tiene una abierta (asignada por el central y no documentada, o asignada
  en SharePoint a su nombre y sin Est_Seg final).
* Primero al que lleva mas tiempo sin recibir. Se asigna la solicitud libre mas antigua.

Estado (dict, se guarda como JSON):
    {"pems": {nombre: {"token", "disponible", "latido", "ultimo"}},
     "asignaciones": {id: {"pem", "asignada_en", "datos", "cerrada_en", "estado"}}}
"""
import secrets
from datetime import datetime

from . import cola

LATIDO_MAX_S = 60          # sin latido en este tiempo = aplicacion cerrada o sin red: no recibe


def nuevo_estado():
    return {"pems": {}, "asignaciones": {}}


def _iso(d):
    return d.isoformat(timespec="seconds")


def _dt(iso):
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------- PEM
def agregar_pem(estado, nombre):
    """Agrega un PEM (nombre EXACTO de PEM_ASIGNADO) y devuelve su token (se le entrega a esa persona)."""
    nombre = " ".join(str(nombre or "").split())
    if not nombre:
        raise ValueError("Falta el nombre")
    for n, p in estado["pems"].items():
        if cola._plano(n) == cola._plano(nombre):
            return p["token"]
    token = secrets.token_urlsafe(24)
    estado["pems"][nombre] = {"token": token, "disponible": False, "latido": "", "ultimo": ""}
    return token


def quitar_pem(estado, nombre):
    estado["pems"].pop(nombre, None)


def nuevo_token(estado, nombre):
    p = estado["pems"][nombre]
    p["token"] = secrets.token_urlsafe(24)
    return p["token"]


def autenticar(estado, token):
    """Nombre del PEM dueno del token, o None. Comparacion en tiempo constante."""
    if not token:
        return None
    for n, p in estado["pems"].items():
        if secrets.compare_digest(str(p.get("token", "")), str(token)):
            return n
    return None


def conectado(p, ahora, max_s=LATIDO_MAX_S):
    t = _dt(p.get("latido"))
    return bool(t) and (ahora - t).total_seconds() <= max_s


# ---------------------------------------------------------------------------------------------- reparto
def abiertas_de(estado, nombre):
    return [i for i, a in estado["asignaciones"].items() if a["pem"] == nombre and not a.get("cerrada_en")]


def ocupados(estado, items):
    """Nombres (planos) con una solicitud abierta: del central o de SharePoint (asignada a su nombre, sin Est_Seg
    final y que el central no haya cerrado ya porque el PEM la documento)."""
    out = {cola._plano(a["pem"]) for a in estado["asignaciones"].values() if not a.get("cerrada_en")}
    cerradas = {i for i, a in estado["asignaciones"].items() if a.get("cerrada_en")}
    for it in items:
        d = cola.desde_sp(it)
        pem = cola._plano(d.get("pem"))
        if not pem or d["id"] in cerradas:
            continue
        if cola._plano(d.get("est_seg")) in cola.ESTADOS_FINALES:
            continue
        for n in estado["pems"]:
            if cola.es_mia(d, n):
                out.add(cola._plano(n))
    return out


def plan(estado, items, ahora):
    """[(item, nombre)] a asignar ahora."""
    ya = set(estado["asignaciones"])
    libres = sorted((it for it in items if cola.es_libre(it) and str(it.get("ID")) not in ya),
                    key=lambda i: str(i.get("Created") or ""))
    ocup = ocupados(estado, items)
    candidatos = [n for n, p in estado["pems"].items()
                  if p.get("disponible") and conectado(p, ahora) and cola._plano(n) not in ocup]
    candidatos.sort(key=lambda n: estado["pems"][n].get("ultimo") or "")
    return list(zip(libres, candidatos))


def registrar_asignacion(estado, item, nombre, ahora):
    d = cola.desde_sp(item)
    d["pem"] = nombre
    estado["asignaciones"][d["id"]] = {"pem": nombre, "asignada_en": _iso(ahora), "datos": d,
                                       "cerrada_en": "", "estado": ""}
    estado["pems"][nombre]["ultimo"] = _iso(ahora)


def cerrar_por_sp(estado, items, ahora):
    """Si en SharePoint la solicitud ya quedo con Est_Seg final (la cerro alguien a mano), se cierra aqui."""
    por_id = {str(it.get("ID")): it for it in items}
    for i, a in estado["asignaciones"].items():
        it = por_id.get(i)
        if it and not a.get("cerrada_en") and cola._plano(it.get("Est_Seg")) in cola.ESTADOS_FINALES:
            a["cerrada_en"], a["estado"] = _iso(ahora), str(it.get("Est_Seg"))


# ---------------------------------------------------------------------------------------------- latido
def latido(estado, nombre, disponible, documentadas, ahora):
    """El PEM avisa que esta conectado. `documentadas` = {id: estado} de las que ya documento.
    Devuelve (casos, pedir_sp): sus casos abiertos (para su cola) y los Est_Seg que el central debe escribir."""
    p = estado["pems"][nombre]
    p["latido"], p["disponible"] = _iso(ahora), bool(disponible)
    pedir_sp = {}
    for i, est in (documentadas or {}).items():
        a = estado["asignaciones"].get(str(i))
        if a is None or a["pem"] != nombre:
            continue                                  # solo puede cerrar las suyas
        if not a.get("cerrada_en"):
            a["cerrada_en"], a["estado"] = _iso(ahora), str(est)
        pedir_sp[str(i)] = str(est)
    casos = []
    for i in abiertas_de(estado, nombre):
        a = estado["asignaciones"][i]
        caso = dict(a["datos"])
        if a.get("correo"):
            caso["_correo"] = a["correo"]          # {"texto", "recibido"}: la plantilla completa del correo
        casos.append(caso)
    return casos, pedir_sp


# ---------------------------------------------------------------------------------------------- correo
def pendientes_correo(estado):
    """{RR: {"id"}} de las asignaciones abiertas que aun no tienen su correo (para el lector central)."""
    out = {}
    for i, a in estado["asignaciones"].items():
        if a.get("cerrada_en") or a.get("correo"):
            continue
        rr = cola.solo_digitos(a["datos"].get("rr"))
        if rr:
            out[rr] = {"id": i, "pem": a["pem"]}
    return out


def guardar_correo(estado, id_, texto, recibido):
    """Une el correo (ya confirmado por SOLICITUD ID) con su asignacion. True si se guardo."""
    a = estado["asignaciones"].get(str(id_))
    if not a or not texto:
        return False
    a["correo"] = {"texto": texto, "recibido": recibido or ""}
    return True


def resumen(estado, ahora):
    """Filas para mostrar: nombre, conectado, disponible, solicitud abierta, ultima asignacion."""
    filas = []
    for n, p in sorted(estado["pems"].items()):
        ab = abiertas_de(estado, n)
        filas.append({"pem": n, "conectado": conectado(p, ahora), "disponible": bool(p.get("disponible")),
                      "abierta": ab[0] if ab else "", "ultimo": p.get("ultimo") or "",
                      "correo": bool(ab and estado["asignaciones"][ab[0]].get("correo"))})
    return filas
