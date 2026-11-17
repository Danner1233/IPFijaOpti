# -*- coding: utf-8 -*-
"""Validaciones minimas compartidas (portadas de Hendrix GPON)."""
import re

RE_NOMBRE_EQUIPO = re.compile(r"^[A-Za-z0-9_.+\-]+$")
RE_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def es_ipv4(texto: str) -> bool:
    if not RE_IPV4.match(texto or ""):
        return False
    return all(int(o) <= 255 for o in texto.split("."))
