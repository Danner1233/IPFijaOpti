# -*- coding: utf-8 -*-
"""Evidencia PREVIA / CONFIGURADO de SWITCH, VELOCIDAD y BRIDGE para la plantilla.

El script de SecureCRT solo entrega las salidas crudas de los equipos (res["raw"]);
aqui se interpretan (logica portada de FlujoHAC.evidencias / FlujoZAC.evidencias de Hendrix GPON).
"""
from . import hw

PUERTO_BRIDGE = "4"
SIN_BRIDGE = "No aplica (la solicitud no requiere IP bridge)."
CLAVES = ("previa_switch", "config_switch", "previa_velocidad", "config_velocidad",
          "previa_bridge", "config_bridge")


def _bridge(res) -> bool:
    return str(res.get("bridge", "")).upper() in ("SI", "SÍ", "TRUE", "1")


def _hac(res: dict) -> dict:
    raw = res.get("raw") or {}
    nombre = res.get("capa2", "")
    v = res.get("velocidad", "")
    ont_id = res.get("ont_id", "")
    ev = {k: "" for k in CLAVES}

    ont_desc = hw.obtener_descripcion_ont(raw.get("salida_ont", ""))
    ev["previa_switch"] = "\n".join(x for x in (
        nombre, "Descripción de la ONT: {}".format(ont_desc) if ont_desc else "") if x)

    fp = hw.obtener_fila_vlan_201(raw.get("salida_service", ""))
    if fp:
        lineas = ["service-port {} (VLAN 201): RX TID {} / TX TID {}".format(fp["index"], fp["rx"], fp["tx"])]
        for tid in dict.fromkeys([fp["rx"], fp["tx"]]):
            d = hw.describir_tid(raw.get("salida_traffic", ""), tid)
            if d:
                lineas.append(d)
        ev["previa_velocidad"] = "\n".join(lineas)

    if not _bridge(res):
        ev["previa_bridge"] = ev["config_bridge"] = SIN_BRIDGE
    else:
        ev["previa_bridge"] = (hw.fila_eth_puerto(raw.get("bridge_pre", ""), ont_id, PUERTO_BRIDGE)
                               or hw.limpiar_salida(raw.get("bridge_pre", "")))

    if res.get("configurado"):
        ev["config_switch"] = "\n".join([nombre, "Descripción configurada: {}".format(res.get("descripcion", "")),
                                         res.get("cmd_descripcion", "")])
        ev["config_velocidad"] = "\n".join([
            res.get("cmd_velocidad", ""),
            "RX TID {} (INTERNET-BA-IP-{}M-DOWN) / TX TID {} (INTERNET-BA-IP-{}M-UP) — {} Mbps".format(
                res.get("tid_down", ""), v, res.get("tid_up", ""), v, v)])
        if _bridge(res):
            post = (hw.fila_eth_puerto(raw.get("bridge_post", ""), ont_id, PUERTO_BRIDGE)
                    or hw.limpiar_salida(raw.get("bridge_post", "")))
            ev["config_bridge"] = "\n".join([res.get("cmd_bridge", ""), post]).strip()
    return ev


def _zac(res: dict) -> dict:
    raw = res.get("raw") or {}
    nombre = res.get("capa2", "")
    ev = {k: "" for k in CLAVES}
    nom = r"^\s*(name|description)\s+\S"
    previos = hw.lineas_que_coinciden(raw.get("gpon_pre", ""), nom)
    ev["previa_switch"] = "\n".join([nombre] + (previos or ["(sin nombre/descripción configurados)"]))
    ev["previa_velocidad"] = "\n".join(
        hw.lineas_que_coinciden(raw.get("vport_pre", ""), r"^\s*service-port\s+\S") or ["(sin service-port previo)"])

    if not _bridge(res):
        ev["previa_bridge"] = ev["config_bridge"] = SIN_BRIDGE
    else:
        previo_b = (hw.lineas_que_coinciden(raw.get("gpon_pre", ""), r"^\s*vlan port\s+\S")
                    + hw.lineas_que_coinciden(raw.get("vport_pre", ""), r"^\s*security\s+\S"))
        ev["previa_bridge"] = "\n".join(previo_b or ["(sin configuración de bridge previa)"])

    if res.get("configurado"):
        d = res.get("descripcion", "")
        ev["config_switch"] = "\n".join([nombre, "name {}".format(d), "description {}".format(d)])
        ev["config_velocidad"] = res.get("cmd_config", "")
        if _bridge(res):
            post = (hw.lineas_que_coinciden(raw.get("vport_post", ""), r"^\s*security\s+\S")
                    + hw.lineas_que_coinciden(raw.get("gpon_post", "") or raw.get("gpon_bridge_post", ""),
                                              r"^\s*vlan port\s+\S"))
            lineas = [res.get("cmd_security", ""), res.get("cmd_bridge", "")] + post
            ev["config_bridge"] = "\n".join(dict.fromkeys(x for x in lineas if x))
    return ev


def construir(res: dict) -> dict:
    """Devuelve las 6 claves previa_*/config_* (vacias si no hubo flujo HAC/ZAC)."""
    tipo = (res.get("tipo_capa2") or "").upper()
    if tipo == "HAC" and res.get("raw"):
        return _hac(res)
    if tipo == "ZAC" and res.get("raw"):
        return _zac(res)
    return {k: "" for k in CLAVES}
