# -*- coding: utf-8 -*-
"""Una sola ventana de trabajo: la que abre el script de SecureCRT.

* La ventana del script avisa que esta viva (`latir`) y revisa si le llego un caso (`tomar_caso`).
* Quien quiera procesar una solicitud de la cola (p. ej. el Centro de control) NO abre otro SecureCRT:
  si hay una ventana viva le pasa el caso con `enviar_caso`.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from .rutas import data_dir

VIVA_S = 15           # una ventana que no late hace mas de esto se considera cerrada


def _ruta(nombre: str):
    return data_dir() / nombre


def _escribir(nombre: str, datos: dict) -> None:
    destino = _ruta(nombre)
    tmp = destino.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, destino)


def latir() -> None:
    _escribir("gui_activa.json", {"pid": os.getpid(), "t": time.time()})


def apagar() -> None:
    try:
        _ruta("gui_activa.json").unlink()
    except OSError:
        pass


def hay_ventana_viva() -> bool:
    try:
        t = float(json.loads(_ruta("gui_activa.json").read_text(encoding="utf-8")).get("t", 0))
    except Exception:
        return False
    return time.time() - t <= VIVA_S


def enviar_caso(caso: dict) -> None:
    _escribir("caso_entrante.json", caso)


def tomar_caso() -> Optional[dict]:
    """Devuelve el caso que dejaron para esta ventana (y lo borra), o None."""
    ruta = _ruta("caso_entrante.json")
    try:
        caso = json.loads(ruta.read_text(encoding="utf-8"))
        ruta.unlink()
        return caso
    except Exception:
        return None
