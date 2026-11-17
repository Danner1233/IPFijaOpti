"""Historial de IP de Capa 2 (HAC/ZAC): equipo -> IP que ya funcionó, para reutilizarla si kou no la devuelve.

Un solo archivo JSON en la carpeta de datos de la app (historial_capa2.json). Solo guarda nombre, tipo, IP y
fechas: NUNCA contraseñas ni credenciales. Se puede abrir con el Bloc de notas o compartir tal cual.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .rutas import data_dir
from .validadores import RE_NOMBRE_EQUIPO, es_ipv4

FUENTES = ("importada", "kou", "manual")   # importada = cargada por el usuario (pegada o desde archivo)

_SEPARADOR = re.compile(r"[;,\t| ]+")
_TIPOS = ("HAC", "ZAC")


def parsear_lineas(texto: str):
    """Texto pegado/CSV -> ([(nombre, tipo, ip)], [líneas no reconocidas]).

    Acepta una línea por equipo, en cualquier orden y con separador espacio, tab, coma, punto y coma o barra:
        HAC-MED.CENTRO-01 172.30.1.20
        ZAC-BOG.X;ZAC;172.30.9.5
    El tipo (HAC/ZAC) se toma de la columna si viene, o del prefijo del nombre. Líneas vacías o con # se omiten.
    """
    validos, invalidas = [], []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        tokens = [t.strip().strip("\"'") for t in _SEPARADOR.split(linea) if t.strip()]
        ips = [t for t in tokens if es_ipv4(t)]
        resto = [t for t in tokens if not es_ipv4(t)]
        tipo = next((t.upper() for t in resto if t.upper() in _TIPOS), "")
        nombres = [t for t in resto if t.upper() not in _TIPOS and RE_NOMBRE_EQUIPO.match(t)]
        if len(ips) != 1 or len(nombres) != 1:
            invalidas.append(linea)
            continue
        nombre = nombres[0].upper()
        validos.append((nombre, tipo or next((t for t in _TIPOS if nombre.startswith(t)), ""), ips[0]))
    return validos, invalidas


class HistorialCapa2:
    def __init__(self, ruta=None):
        self.ruta = Path(ruta) if ruta else data_dir() / "historial_capa2.json"
        self._lock = threading.Lock()

    @staticmethod
    def _clave(nombre: str) -> str:
        return (nombre or "").strip().upper()

    def _leer(self) -> Dict[str, dict]:
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except Exception:
            return {}

    def _escribir(self, datos: Dict[str, dict]) -> None:
        tmp = self.ruta.with_suffix(".tmp")
        txt = json.dumps(datos, ensure_ascii=False, indent=1, sort_keys=True)
        for intento in range(40):          # Windows puede bloquear el archivo unos ms (antivirus/indexador)
            try:
                tmp.write_text(txt, encoding="utf-8")
                os.replace(tmp, self.ruta)
                return
            except OSError:
                if intento == 39:
                    raise
                time.sleep(0.03)

    def buscar(self, nombre: str) -> Optional[dict]:
        """Registro del equipo (copia) o None."""
        with self._lock:
            reg = self._leer().get(self._clave(nombre))
        if reg and es_ipv4(str(reg.get("ip", ""))):
            return dict(reg)
        return None

    def registrar(self, nombre: str, tipo: str, ip: str, fuente: str = "kou") -> bool:
        """Guarda/actualiza la IP que funcionó. Devuelve False si el dato no es válido o no se pudo escribir."""
        clave = self._clave(nombre)
        if not clave or not es_ipv4(ip or ""):
            return False
        ahora = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                datos = self._leer()
                prev = datos.get(clave) or {}
                misma = prev.get("ip") == ip
                datos[clave] = {
                    "nombre": clave, "tipo": tipo or prev.get("tipo", ""), "ip": ip, "fuente": fuente,
                    "veces": (int(prev.get("veces", 0)) + 1) if misma else 1,
                    "primera": prev.get("primera") if misma and prev.get("primera") else ahora,
                    "ultima": ahora,
                }
                if prev and not misma:
                    datos[clave]["ip_anterior"] = prev.get("ip", "")
                self._escribir(datos)
            return True
        except Exception:
            return False          # el historial es una ayuda: jamás debe romper una operación

    def listar(self) -> List[dict]:
        with self._lock:
            regs = list(self._leer().values())
        return sorted(regs, key=lambda d: d.get("ultima", ""), reverse=True)

    def eliminar(self, nombre: str) -> bool:
        with self._lock:
            datos = self._leer()
            if datos.pop(self._clave(nombre), None) is None:
                return False
            self._escribir(datos)
        return True

    def importar_texto(self, texto: str, fuente: str = "importada") -> dict:
        """Agrega/actualiza desde texto (ver parsear_lineas). Devuelve el resumen de lo ocurrido."""
        validos, invalidas = parsear_lineas(texto)
        res = {"nuevas": 0, "actualizadas": 0, "iguales": 0, "invalidas": invalidas}
        for nombre, tipo, ip in validos:
            previo = self.buscar(nombre)
            if previo and previo["ip"] == ip:
                res["iguales"] += 1
                continue
            if self.registrar(nombre, tipo, ip, fuente):
                res["actualizadas" if previo else "nuevas"] += 1
            else:
                res["invalidas"].append("{} {}".format(nombre, ip))
        return res

    def importar_archivo(self, ruta, fuente: str = "importada") -> dict:
        """.txt/.csv (una línea por equipo) o un historial_capa2.json de esta misma app."""
        ruta = Path(ruta)
        txt = ruta.read_text(encoding="utf-8-sig", errors="replace")
        if ruta.suffix.lower() == ".json":
            try:
                datos = json.loads(txt)
                regs = datos.values() if isinstance(datos, dict) else datos
                txt = "\n".join("{} {} {}".format(d.get("nombre", ""), d.get("tipo", ""), d.get("ip", ""))
                                for d in regs if isinstance(d, dict))
            except Exception:
                return {"nuevas": 0, "actualizadas": 0, "iguales": 0, "invalidas": ["(JSON ilegible)"]}
        return self.importar_texto(txt, fuente)
