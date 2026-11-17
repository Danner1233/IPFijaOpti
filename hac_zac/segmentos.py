"""Segmentos de red de una interfaz y cuál tiene más IP libres.

Una IP "libre" es la que el ARP muestra como Incomplete (definición del script original),
dentro del segmento y sin contar red, broadcast ni la IP de la propia interfaz (gateway).
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_RE_IP_ADDR = re.compile(
    r"^\s*ip\s+address\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d{1,3}(?:\.\d{1,3}){3})(?:\s+sub)?\s*$",
    re.IGNORECASE | re.MULTILINE)


@dataclass
class Segmento:
    red: str                    # 190.84.10.0/24
    prefijo: int
    mascara: str
    gateway: str
    libres: List[str] = field(default_factory=list)

    @property
    def n_libres(self) -> int:
        return len(self.libres)

    def a_dict(self) -> dict:
        return {"red": self.red, "prefijo": self.prefijo, "mascara": self.mascara,
                "gateway": self.gateway, "libres": list(self.libres), "n_libres": self.n_libres}


def obtener_direcciones_interfaz(salida_config: str) -> List[Tuple[str, str]]:
    """Todas las 'ip address X M' (principal y '... sub') de la configuración de la interfaz."""
    return [(m.group(1), m.group(2)) for m in _RE_IP_ADDR.finditer(salida_config or "")]


def calcular_segmentos(salida_config: str, ips_libres: List[str]) -> List[Segmento]:
    """Segmentos ordenados de más a menos IP libres (empate: el orden de la configuración)."""
    segmentos: List[Segmento] = []
    vistos = set()
    for ip, mask in obtener_direcciones_interfaz(salida_config):
        try:
            iface = ipaddress.ip_interface("{}/{}".format(ip, mask))
        except ValueError:
            continue
        red = iface.network
        if red in vistos:
            continue
        vistos.add(red)
        libres = []
        for cand in ips_libres or []:
            try:
                a = ipaddress.IPv4Address(cand)
            except ValueError:
                continue
            if a in red and a not in (red.network_address, red.broadcast_address, iface.ip):
                libres.append(cand)
        libres = sorted(set(libres), key=lambda s: int(ipaddress.IPv4Address(s)))
        segmentos.append(Segmento(str(red), red.prefixlen, str(red.netmask), str(iface.ip), libres))
    orden = {s.red: i for i, s in enumerate(segmentos)}
    return sorted(segmentos, key=lambda s: (-s.n_libres, orden[s.red]))


def mejor_segmento(segmentos: List[Segmento]) -> Optional[Segmento]:
    return segmentos[0] if segmentos and segmentos[0].n_libres > 0 else None


def segmento_de_ip(segmentos, ip: str):
    """Segmento (Segmento o dict) que contiene la IP, o None."""
    try:
        a = ipaddress.IPv4Address((ip or "").strip())
    except ValueError:
        return None
    for s in segmentos or []:
        red = s["red"] if isinstance(s, dict) else s.red
        if a in ipaddress.ip_network(red):
            return s
    return None
