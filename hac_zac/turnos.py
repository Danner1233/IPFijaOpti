# -*- coding: utf-8 -*-
"""Turnos rotativos del equipo (8:00 a 20:00). El admin pone a cada PEM una FRANJA por semana y la app sabe su
horario de cada dia:

    Franja     Lun-Jue                Viernes y sabado
    temprano   A  8:00 - 17:30        B  8:00 - 17:00
    medio      C  9:30 - 19:00        D 10:00 - 19:00
    tarde      E 10:30 - 20:00        F 11:00 - 20:00
    (domingo no hay turno)

* Solo recibe solicitudes quien esta EN TURNO.
* CORTE: CORTE_MIN (1 min) antes de salir ya no recibe.
* Sin franja: no hay restriccion de horario (como antes).
Logica pura, sin archivos.
"""
from datetime import datetime, time, timedelta

TURNOS = {"A": ("08:00", "17:30"), "B": ("08:00", "17:00"), "C": ("09:30", "19:00"),
          "D": ("10:00", "19:00"), "E": ("10:30", "20:00"), "F": ("11:00", "20:00")}
FRANJAS = {"temprano": ("A", "B"), "medio": ("C", "D"), "tarde": ("E", "F")}   # (lun-jue, vie-sab)
NOMBRE_FRANJA = {"temprano": "Temprano", "medio": "Medio", "tarde": "Tarde", "": "Sin franja"}
CORTE_MIN = 1         # deja de recibir 1 min antes de su salida
AVISO_MIN = 10        # 10 min antes de salir se avisa si tiene una solicitud abierta


def _h(t):
    hh, mm = t.split(":")
    return time(int(hh), int(mm))


def franja_valida(franja):
    f = str(franja or "").strip().lower()
    return f if f in FRANJAS else ""


def turno_del_dia(franja, dia):
    """Letra del turno ese dia (A-F) o None (domingo / sin franja)."""
    f = franja_valida(franja)
    if not f:
        return None
    wd = dia.weekday()                    # 0 lunes ... 6 domingo
    if wd == 6:
        return None
    return FRANJAS[f][0] if wd <= 3 else FRANJAS[f][1]


def horario(franja, dia):
    """(inicio, fin) como datetime de ese dia, o None."""
    letra = turno_del_dia(franja, dia)
    if not letra:
        return None
    d = dia.date() if isinstance(dia, datetime) else dia
    ini, fin = TURNOS[letra]
    return datetime.combine(d, _h(ini)), datetime.combine(d, _h(fin))


def situacion(franja, ahora=None, corte_min=CORTE_MIN):
    """'sin_franja' | 'en_turno' | 'corte' (en turno pero ya no recibe) | 'antes' | 'fuera' (ya salio / no trabaja)."""
    ahora = ahora or datetime.now()
    if not franja_valida(franja):
        return "sin_franja"
    h = horario(franja, ahora)
    if not h:
        return "fuera"
    ini, fin = h
    if ahora < ini:
        return "antes"
    if ahora >= fin:
        return "fuera"
    if ahora >= fin - timedelta(minutes=corte_min):
        return "corte"
    return "en_turno"


def puede_recibir(franja, ahora=None):
    return situacion(franja, ahora) in ("en_turno", "sin_franja")


def fuera_de_turno(franja, ahora=None):
    return situacion(franja, ahora) in ("antes", "fuera")


def aviso_salida(franja, ahora=None, aviso_min=AVISO_MIN):
    """True en los ultimos `aviso_min` minutos del turno (para avisar si tiene una solicitud abierta)."""
    ahora = ahora or datetime.now()
    h = horario(franja, ahora)
    return bool(h) and h[1] - timedelta(minutes=aviso_min) <= ahora < h[1]


# ---------------------------------------------------------------------------------------------- lista para elegir
DIAS = {"A": "LUNES - JUEVES", "B": "VIERNES", "C": "LUNES - JUEVES", "D": "VIERNES", "E": "LUNES - JUEVES",
        "F": "VIERNES"}


def _ampm(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def opcion(letra):
    """'TURNO A   (8:00 AM - 5:30 PM)   LUNES - JUEVES' (como lo maneja el equipo)."""
    ini, fin = TURNOS[letra]
    return "TURNO %s   (%s - %s)   %s" % (letra, _ampm(ini), _ampm(fin), DIAS[letra])


def lista_turnos():
    return [(l, opcion(l)) for l in sorted(TURNOS)]


def franja_de_letra(letra):
    """A/B -> temprano, C/D -> medio, E/F -> tarde ('' si no es un turno)."""
    l = str(letra or "").strip().upper()
    for f, par in FRANJAS.items():
        if l in par:
            return f
    return ""


def hay_turno(dia):
    """Ese dia se trabaja por turnos (lunes a sabado)."""
    return dia.weekday() != 6


def texto(franja, ahora=None):
    """'Turno A 8:00–17:30' / 'Sin turno hoy' / ''."""
    ahora = ahora or datetime.now()
    if not franja_valida(franja):
        return ""
    letra = turno_del_dia(franja, ahora)
    if not letra:
        return "Sin turno hoy"
    ini, fin = TURNOS[letra]
    return "Turno %s %s–%s" % (letra, ini.lstrip("0"), fin)
