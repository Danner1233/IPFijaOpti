# -*- coding: utf-8 -*-
"""Convierte el resultado del script (RES) en el registro de operacion del historial.

El formato de 'operacion' es el mismo de OperationResult.to_dict() de Hendrix GPON, de modo que
las solicitudes guardadas aqui y las de Hendrix son intercambiables.
"""
from datetime import datetime

from . import estados, evidencias, hw
from .segmentos import calcular_segmentos, mejor_segmento

URL_VALIDACION_RED = {"ATP": "http://100.123.40.145:8100/", "ONNET": "https://cxm.onnetfibra.co:6443/"}
URL_NETCRACKER = "https://100.123.26.55/login.jsp"
URL_CASO_BRIDGE = {
    "ONNET": ("TCO", "https://oncoprod.service-now.com/customer"),
    "ATP": ("INCLA", "https://atpsitesfiber.atlassian.net/"),
}


def estado_de(fase: str, res: dict) -> str:
    """Valor de RunStatus para el intento (exito, advertencia, error, cancelado, consulta_sin_config)."""
    if fase == "error":
        return "error"
    if fase == "cancelado":
        return "cancelado"
    if res.get("configurado"):
        return "advertencia" if str(res.get("verificacion", "")).upper() == "REVISAR" else "exito"
    return "consulta_sin_config"


def intento(fase: str, res: dict, mensaje: str, inicio: str) -> dict:
    return {
        "inicio": inicio, "estado": estado_de(fase, res), "mensaje": (mensaje or "")[:300],
        "red": hw.clasificar_red(res.get("tipo_capa2"), res.get("capa2")),
        "solo_consulta": False, "configuro": bool(res.get("configurado")),
    }


def operacion(fase: str, res: dict, mensaje: str, inicio: str, fin: str = "") -> dict:
    """Estructura compatible con OperationResult.to_dict()."""
    bloque = res.get("bloque_interfaz", "") or ""
    libres = list(res.get("ips_libres") or [])
    segs = calcular_segmentos(bloque, libres)
    mejor = mejor_segmento(segs)
    tipo = res.get("tipo_capa2") or ""
    ev = evidencias.construir(res)
    return {
        "entrada": {
            "ont_ip": res.get("ip_ont", ""), "sn": res.get("serial", ""), "velocidad": res.get("velocidad", ""),
            "bridge": str(res.get("bridge", "")).upper() == "SI", "cliente": res.get("cliente", ""),
            "cuenta_rr": res.get("rr", ""), "descripcion": res.get("descripcion", ""), "solo_consulta": False,
        },
        "estado": estado_de(fase, res), "mensaje": mensaje or "", "errores": [], "advertencias": [],
        "capa3_inicial": res.get("capa3_inicial", ""), "capa3_ip": res.get("capa3", ""),
        "interfaz_encontrada": res.get("interfaz_encontrada", ""), "interfaz": res.get("interfaz", ""),
        "capa2_nombre": res.get("capa2", "") if res.get("capa2") != "No identificado" else "",
        "capa2_tipo": tipo, "capa2_ip": res.get("ip_capa2", ""), "gateway": res.get("gateway", ""),
        "mascara": res.get("mascara", ""), "destination_mask": res.get("destination_mask", ""),
        "flujo": tipo if tipo in ("HAC", "ZAC") else "SIN_FLUJO",
        "tipo_red": hw.clasificar_red(tipo, res.get("capa2")), "validacion_red": "",
        "segmentos": [s.a_dict() for s in segs], "segmento_mejor": mejor.a_dict() if mejor else {},
        "vlan": "201", "ips_libres": libres, "ips_libres_final": list(res.get("ips_libres_final") or []),
        "fs_p": res.get("fs_p", ""), "ont_id": res.get("ont_id", ""), "service_port": res.get("service_port", ""),
        "tid_down": res.get("tid_down", ""), "tid_up": res.get("tid_up", ""), "cir": str(res.get("cir", "") or ""),
        "gpon": res.get("gpon", ""), "vport": res.get("vport", ""),
        "previa_switch": ev["previa_switch"], "config_switch": ev["config_switch"],
        "previa_velocidad": ev["previa_velocidad"], "config_velocidad": ev["config_velocidad"],
        "previa_bridge": ev["previa_bridge"], "config_bridge": ev["config_bridge"],
        "comandos_planificados": [], "comandos_aplicados": list(res.get("comandos_aplicados") or []),
        "verificaciones": [{"nombre": "Verificación", "ok": str(res.get("verificacion", "")).upper() != "REVISAR",
                            "detalle": str(res.get("verificacion", ""))}] if res.get("verificacion") else [],
        "bloque_interfaz": bloque, "inicio": inicio, "fin": fin or datetime.now().isoformat(timespec="seconds"),
    }


def texto_acs(portal: dict) -> str:
    """Bloque 'ACS CLIENT INFORMATION' armado con lo que devolvio el Support Portal (sin pegar nada)."""
    crudo = (portal or {}).get("crudo") or {}
    orden = ["User name", "User location", "mycust03", "mycust04", "Serial number", "Manufacturer",
             "Manufacturer OUI", "Product class", "Hardware version", "Firmware version", "IP address", "Mac address"]
    lineas = ["{}: {}".format(k, crudo[k]) for k in orden if k in crudo]
    return "\n".join(lineas)
