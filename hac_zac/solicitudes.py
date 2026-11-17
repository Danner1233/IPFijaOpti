"""Historial de solicitudes: un archivo JSON por solicitud con todo lo necesario para reabrir su plantilla.

Guarda lo que usted pegó (solicitud y ACS), la plantilla tal como quedó, las IP elegidas y el resultado de la
operación (segmentos, evidencias, Capa 2…). NUNCA guarda contraseñas ni credenciales.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .rutas import data_dir


def plantilla_guardada(d: dict) -> Optional[bool]:
    """True si la plantilla de la solicitud esta en su .txt tal como se ve; False si no; None si aun no hay
    plantilla (nada que guardar)."""
    texto = d.get("preview") or ""
    if not str(texto).strip():
        return None
    from .plantilla import esta_guardada
    return esta_guardada(texto, d.get("archivo"))


def _tiempo_resumen(d: dict, sol_cola: Optional[dict]) -> dict:
    """Tiempo de gestion para el historial: '18/15 min ⚠ · fotos', 'excedido' y el tipo de justificacion."""
    from . import tiempos
    try:
        m = tiempos.medir(d, sol_cola)
    except Exception:
        return {"tiempo": "—", "excedido": False, "demora_tipo": ""}
    j = d.get("demora") or {}
    tipos = {"fotos": "fotos", "observacion": "observación", "pem": "demora PEM"}
    txt = tiempos.texto(m)
    if m["excedido"] and j.get("tipo"):
        txt += " · " + tipos.get(j["tipo"], j["tipo"])
    return {"tiempo": txt, "excedido": m["excedido"], "demora_tipo": j.get("tipo", "")}


class SolicitudStore:
    def __init__(self, carpeta=None):
        self.carpeta = Path(carpeta) if carpeta else data_dir() / "solicitudes"
        self.carpeta.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def clave(solicitud_id: str, rr: str) -> str:
        """El N.º de solicitud identifica el registro; si falta, la cuenta RR."""
        sid, rr = (solicitud_id or "").strip(), (rr or "").strip()
        return sid or ("RR" + rr if rr else "")

    def _ruta(self, key: str) -> Path:
        return self.carpeta / (re.sub(r"[^A-Za-z0-9_\-]", "_", key) + ".json")

    def cargar(self, key: str) -> Optional[dict]:
        try:
            return json.loads(self._ruta(key).read_text(encoding="utf-8"))
        except Exception:
            return None

    def guardar(self, rec: dict) -> str:
        key = rec.get("key") or self.clave(rec.get("id", ""), rec.get("rr", ""))
        if not key:
            raise ValueError("La solicitud no tiene ID ni cuenta RR.")
        ahora = datetime.now().isoformat(timespec="seconds")
        previo = self.cargar(key) or {}
        rec = dict(rec, key=key, creada=previo.get("creada") or ahora, actualizada=ahora)
        tmp = self._ruta(key).with_suffix(".tmp")
        datos = json.dumps(rec, ensure_ascii=False, indent=1)
        for intento in range(40):           # Windows puede bloquear el archivo unos ms (antivirus/indexador)
            try:
                tmp.write_text(datos, encoding="utf-8")
                os.replace(tmp, self._ruta(key))
                break
            except OSError:
                if intento == 39:
                    raise
                time.sleep(0.03)
        return key

    def eliminar(self, key: str) -> None:
        try:
            self._ruta(key).unlink()
        except FileNotFoundError:
            pass

    def listar(self) -> List[dict]:
        """Resumen de cada solicitud, la más reciente primero."""
        out = []
        try:
            from . import cola
            asignadas = {s["id"]: s for s in cola.solicitudes()}
        except Exception:
            asignadas = {}
        for f in self.carpeta.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            resumen = {k: d.get(k, "") for k in ("key", "id", "rr", "cliente", "red", "capa2", "estado",
                                                 "resultado", "creada", "actualizada", "documentada_en", "causa")}
            if not isinstance(resumen["resultado"], str):      # formato anterior: 'resultado' era el dict de la operación
                resumen["resultado"] = ""
            from .estados import normalizar
            resumen["resultado"] = normalizar(resumen["resultado"])
            resumen["intentos"] = d.get("intentos") or []
            resumen["guardada"] = plantilla_guardada(d)
            resumen.update(_tiempo_resumen(d, asignadas.get(str(d.get("id") or ""))))
            out.append(resumen)
        return sorted(out, key=lambda r: r.get("actualizada", ""), reverse=True)
