# -*- coding: utf-8 -*-
"""Tiempo de gestion de cada solicitud, con limite segun la red.

* Corre desde que la solicitud se ASIGNA (cola: asignada_en, cuando el lector la toma con mi nombre). Si no paso
  por la cola (solicitud pegada a mano), desde que se creo el registro en el historial.
* Termina al DOCUMENTAR.
* Limite: red CLARO 15 min; redes neutras (ATP / ONNET) 30 min.
* Si se pasa, para documentar hay que justificar: CLARO con fotos (max. 5); neutras con observacion. En ambos casos
  se puede elegir "Demora por parte del PEM".
"""
from datetime import datetime

LIMITE_CLARO_MIN = 15
LIMITE_NEUTRA_MIN = 30
MAX_FOTOS = 5
DEMORA_PEM = "Demora por parte del PEM"
ALERTA = "Superó el tiempo de gestión · baja productividad"
MEDIR_DESDE = datetime(2026, 11, 17)   # las solicitudes de antes no se miden (no existia la medicion)


def _dt(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def red_de(rec):
    """'CLARO', 'ATP' u 'ONNET'. Primero la PROPIEDAD RED de la solicitud; si no, la red del Capa 2. Sin dato: CLARO."""
    from . import plantilla
    prop = ""
    if rec.get("txt_sol"):
        try:
            prop = plantilla.parsear_solicitud(rec["txt_sol"]).get("propiedad_red", "")
        except Exception:
            prop = ""
    for fuente in (prop, rec.get("propiedad_red"), rec.get("red")):
        f = str(fuente or "").upper()
        if "ONNET" in f or "ON NET" in f:
            return "ONNET"
        if "ATP" in f:
            return "ATP"
        if "CLARO" in f:
            return "CLARO"
    return "CLARO"


def es_neutra(red):
    return red in ("ATP", "ONNET")


def limite_min(red):
    return LIMITE_NEUTRA_MIN if es_neutra(red) else LIMITE_CLARO_MIN


def inicio_de(rec, sol_cola=None):
    """Hora de inicio: asignacion en la cola; si no, creacion del registro."""
    for v in ((sol_cola or {}).get("asignada_en"), rec.get("asignada_en"), rec.get("creada")):
        d = _dt(v)
        if d:
            return d if d >= MEDIR_DESDE else None
    return None


def medir(rec, sol_cola=None, ahora=None):
    """{'red','limite','inicio','minutos','excedido','fin'}. Si ya se documento, mide hasta esa hora."""
    red = red_de(rec)
    lim = limite_min(red)
    ini = inicio_de(rec, sol_cola)
    fin = _dt(rec.get("documentada_en")) or ahora or datetime.now()
    minutos = max(0.0, (fin - ini).total_seconds() / 60.0) if ini else 0.0
    return {"red": red, "limite": lim, "inicio": ini, "minutos": minutos, "excedido": bool(ini) and minutos > lim,
            "fin": fin if rec.get("documentada_en") else None}


def texto(m):
    """'12/15 min' o '22/15 min ⚠'."""
    if not m["inicio"]:
        return "—"
    return "%d/%d min%s" % (int(m["minutos"]), m["limite"], " ⚠" if m["excedido"] else "")


def justificacion_valida(red, j):
    """La justificacion que exige la red (o 'Demora por parte del PEM'). Devuelve (ok, mensaje)."""
    j = j or {}
    if j.get("tipo") == "pem":
        return True, ""
    if es_neutra(red):
        if len(str(j.get("observacion") or "").strip()) < 10:
            return False, "Escriba la observación de la demora (mínimo 10 caracteres)."
        return True, ""
    fotos = [f for f in (j.get("fotos") or []) if f]
    if not fotos:
        return False, "Adjunte al menos una foto que explique la demora (máximo %d)." % MAX_FOTOS
    if len(fotos) > MAX_FOTOS:
        return False, "Máximo %d fotos." % MAX_FOTOS
    return True, ""


def necesita_justificar(rec, sol_cola=None, ahora=None):
    m = medir(rec, sol_cola, ahora)
    ok, _ = justificacion_valida(m["red"], rec.get("demora"))
    return m["excedido"] and not ok
