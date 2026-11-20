# -*- coding: utf-8 -*-
"""Horas extra del PEM (fuera de su turno), con registro en el reporte del equipo (reportes/<PEM>/<mes>/Horas extra.csv).

Solo cuentan las VOLUNTARIAS: fuera de su turno (o en el corte) el PEM pulsa «⏱ Horas extra» con un motivo y un
tiempo; mientras duren puede recibir solicitudes (hasta CORTE_EXTRA_MIN antes de terminar, para no quedar con una a
medias). Terminar una solicitud despues de la hora de salida NO es hora extra: se la deja terminar y su turno se
cierra al acabarla, pero no se registra.

El tramo en curso se guarda local (extra.json); cada tramo terminado es una fila del reporte.
"""
from datetime import datetime, timedelta

from . import turnos

ARCHIVO = "extra.json"
MINUTOS_EXTRA = (30, 60, 90, 120)
MOTIVOS_EXTRA = ("Muchas solicitudes en cola", "Cubrir a un compañero", "Lo pidió el admin", "Pendientes del día")
CORTE_EXTRA_MIN = 15
SOLICITUD, VOLUNTARIA = "Terminando solicitud", "Voluntaria"
TERMINO, SE_CUMPLIO, LA_TERMINO, CERRO_APP = ("Terminó la solicitud", "Se cumplió el tiempo", "La terminó el PEM",
                                             "Cerró la aplicación")


def _iso(d):
    return d.isoformat(timespec="seconds")


def _dt(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def _leer():
    from . import cola
    e = cola._leer(ARCHIVO, {})
    return e if isinstance(e, dict) else {}


def _escribir(e):
    from . import cola
    cola._escribir(ARCHIVO, e)


def activa(e):
    return bool(isinstance(e, dict) and e.get("desde") and e.get("tipo") == VOLUNTARIA)


def mi_extra():
    """El tramo de horas extra en curso o None."""
    e = _leer()
    return e if activa(e) else None


def recibe(extra, ahora=None):
    """¿Puede recibir solicitudes por estar en horas extra voluntarias?"""
    if not activa(extra) or extra.get("tipo") != VOLUNTARIA:
        return False
    hasta = _dt(extra.get("hasta"))
    return bool(hasta) and (ahora or datetime.now()) < hasta - timedelta(minutes=CORTE_EXTRA_MIN)


def puede_iniciar(franja, ahora=None):
    """Las voluntarias solo fuera del turno (o en su corte); con franja asignada."""
    return bool(turnos.franja_valida(franja)) and not turnos.puede_recibir(franja, ahora)


def _turno(franja, ahora):
    letra = turnos.turno_del_dia(franja, ahora) or ""
    h = turnos.horario(franja, ahora)
    return letra, (h[1].strftime("%H:%M") if h else "")


def iniciar_voluntaria(minutos, motivo="", franja="", ahora=None, carpeta_equipo="", nombre=""):
    ahora = ahora or datetime.now()
    previo = mi_extra()
    if previo:
        terminar(carpeta_equipo, nombre, ahora, LA_TERMINO)
    letra, fin = _turno(franja, ahora)
    e = {"tipo": VOLUNTARIA, "desde": _iso(ahora), "hasta": _iso(ahora + timedelta(minutes=int(minutos))),
         "motivo": " ".join(str(motivo or "").split())[:80], "turno": letra, "fin_turno": fin, "caso": ""}
    _escribir(e)
    return e


def terminar(carpeta_equipo, nombre, cuando, como):
    """Cierra el tramo en curso y lo deja en el reporte. Devuelve la fila escrita (o None)."""
    from . import reportes
    e = _leer()
    if not activa(e):
        return None
    ini = _dt(e["desde"])
    fila = None
    if ini and cuando > ini:
        motivo = e.get("motivo") or ("Solicitud %s" % e["caso"] if e.get("caso") else "")
        fila = [nombre, reportes.fecha(ini), e.get("turno", ""), e.get("fin_turno", ""), reportes.hora(ini),
                reportes.hora(cuando), reportes.minutos(ini, cuando), e["tipo"], motivo,
                como + (" %s" % e["caso"] if como == TERMINO and e.get("caso") else "")]
        reportes.agregar(carpeta_equipo, "horas_extra", nombre, ini, fila)
    _escribir({"cerrado": _iso(cuando)})
    return fila


def seguir(carpeta_equipo, nombre, franja, caso, ahora=None):
    """Se llama cada minuto (con la presencia): cierra las voluntarias cuando se cumple su tiempo (si sigue con una
    abierta, la termina, pero ese rato ya no cuenta). Devuelve el tramo en curso."""
    from . import cola
    ahora = ahora or datetime.now()
    with cola._bloqueo():
        e = _leer()
        if e.get("tipo") == SOLICITUD:                  # version anterior: terminar una solicitud ya no cuenta
            _escribir({})
        elif activa(e):
            hasta = _dt(e.get("hasta"))
            if hasta and ahora >= hasta:
                terminar(carpeta_equipo, nombre, hasta, SE_CUMPLIO)
            elif caso and e.get("caso") != str(caso):
                e["caso"] = str(caso)
                _escribir(e)
    return mi_extra()


def cerrar(carpeta_equipo, nombre, ahora=None):
    """Al cerrar la app: el tramo en curso queda en el reporte."""
    terminar(carpeta_equipo, nombre, ahora or datetime.now(), CERRO_APP)


def texto(extra, ahora=None):
    """'⏱ Horas extra hasta 20:30'."""
    if not activa(extra):
        return ""
    h = _dt(extra.get("hasta"))
    return "⏱ Horas extra" + (" hasta %s" % h.strftime("%H:%M") if h else "")
