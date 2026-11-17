# -*- coding: utf-8 -*-
"""Registro de eventos y errores en un archivo rotativo (hac_zac.log, en la carpeta de datos).

Sirve para no perder errores que antes se tragaban en silencio y para poder pedirle al usuario
un solo archivo cuando algo falla.
"""
import logging
import logging.handlers

from .rutas import data_dir

_LISTO = False


def obtener(nombre: str = "hac_zac") -> logging.Logger:
    """Devuelve un logger; la primera vez configura el archivo (1 MB x 3 copias)."""
    global _LISTO
    raiz = logging.getLogger("hac_zac")
    if not _LISTO:
        _LISTO = True
        raiz.setLevel(logging.INFO)
        try:
            h = logging.handlers.RotatingFileHandler(str(data_dir() / "hac_zac.log"), maxBytes=1_000_000,
                                                     backupCount=3, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            raiz.addHandler(h)
        except OSError:
            raiz.addHandler(logging.NullHandler())      # carpeta sin permiso: no se detiene la app
    return raiz.getChild(nombre) if nombre != "hac_zac" else raiz
