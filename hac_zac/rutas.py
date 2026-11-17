# -*- coding: utf-8 -*-
"""Carpeta de datos (historiales, solicitudes, plantillas base, ajustes).

Por defecto es la carpeta donde estan SCRIPT_HAC_ZAC_UNIFICADO.py y hac_zac_gui.py,
la misma donde el script ya guarda historial_capa2.json. Se puede cambiar con la
variable de entorno HAC_ZAC_DATOS.
"""
import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("HAC_ZAC_DATOS")
    base = Path(override) if override else Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base
