"""Documentación en Microsoft Forms: lectura de la plantilla + registro de cuentas documentadas.

Portado de «automatizador_forms_historial.pyw» (parse, campos obligatorios y registro diario).
Cambios: el texto sale de la plantilla de la app (no se captura Notepad++), y la cuenta RR se
normaliza (62306807.0000000 -> 62306807).
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from .rutas import data_dir

CONFIG_DEFECTO = {
    "form_url": "https://forms.cloud.microsoft/pages/responsepage.aspx?id=uCK7RixM_0CDYHtjNIISeVtBCnbOM4xMkq952NJbQKJUNTdSMTNMRzZDQ0dVV0RIMzlISkdCVkZSMy4u&route=shorturl",
    "regional": {"Antioquia": "1", "Costa": "2", "Centro": "4", "Eje Cafetero": "7", "Occidente": "8", "Oriente": "12"},
    "property_network": {"CLARO": "Red Propia", "ATP": "Red ATP", "ONNET": "Red Onnet"},
    "success_option": "Exitosa",
    "browser_channel": "msedge",
}

ETIQUETAS = {"id": "ID del caso (SOLICITUD ID)", "rr": "Cuenta RR", "regional": "Regional",
             "actividad": "Tipo de actividad", "ip": "IP asignada", "mask": "Máscara", "gw": "Gateway",
             "bridge_ip": "IP bridge", "olt": "CAPA 2 (OLT)", "propiedad": "Propiedad de red",
             "dmz": "IP DMZ", "forward": "IP forwarding", "port": "Puerto port forwarding"}


def cargar_config() -> dict:
    ruta = data_dir() / "documentacion.json"
    if not ruta.exists():
        ruta.write_text(json.dumps(CONFIG_DEFECTO, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        cfg = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    return {**CONFIG_DEFECTO, **cfg}


# ----------------------------------------------------------------------------- análisis del texto
def find_line(label: str, text: str, occurrence: int = 1) -> str:
    """'ETIQUETA: valor' o 'ETIQUETA? valor' en la misma línea (solo espacios horizontales)."""
    pat = r"^[ \t]*" + re.escape(label) + r"[ \t]*:?[ \t]*([^\r\n]*)"
    ms = list(re.finditer(pat, text, re.I | re.M))
    return ms[occurrence - 1].group(1).strip() if len(ms) >= occurrence else ""


def find_after(label: str, text: str) -> str:
    """Valor en la misma línea o en la primera línea no vacía siguiente; si esa línea es otra etiqueta ('...:') -> ''."""
    m = re.search(r"^[ \t]*" + re.escape(label) + r"[ \t]*:?[ \t]*([^\r\n]*)", text, re.I | re.M)
    if not m:
        return ""
    value = m.group(1).strip()
    if value:
        return value
    for line in text[m.end():].splitlines():
        line = line.strip()
        if not line:
            continue
        return "" if line.endswith(":") else line
    return ""


def parse(text: str) -> dict:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    d = {}
    m = re.search(r"\+{3,}[ \t]*SOLICITUD[ \t]+ID[ \t]*:[ \t]*([^\s+]+)", text, re.I)
    d["id"] = m.group(1).strip() if m else ""
    d["rr"] = re.sub(r"\.0+$", "", find_line("CUENTA RR", text))
    d["regional"] = find_line("REGIONAL", text)
    d["actividad"] = find_line("TIPO ACTIVIDAD", text)
    d["propiedad"] = find_line("PROPIEDAD RED", text)
    d["atp"] = find_line("SERVICIO SOBRE ATP?", text)
    d["bridgereq"] = find_line("REQUIERE IP BRIDGE?", text)
    d["dmzreq"] = find_line("REQUIERE DMZ?", text)
    d["portreq"] = find_line("REQUIERE PORT FW?", text)
    if not d["propiedad"]:
        d["propiedad"] = "ATP" if d["atp"].strip().upper() == "SI" else "CLARO"
    # La plantilla pone «NOMBRE - IP»; el formulario (OLT ATP.) espera solo el nombre
    d["olt"] = re.sub(r"[ \t]+-[ \t]+\d{1,3}(?:\.\d{1,3}){3}[ \t]*$", "", find_after("CAPA 2", text))

    m = re.search(r"DIRECCIONAMIENTO[ \t]+FINAL.*?(?=^\s*CAPA[ \t]+2[ \t]*:|^\s*DNS[ \t]+PRIMARIO|\Z)",
                  text, re.I | re.M | re.S)
    final = m.group(0) if m else ""
    d["ip"] = find_after("IPAddress", final)
    d["mask"] = find_after("SubnetMask", final)
    d["gw"] = find_after("X_SKYW_DefaultGateway", final)

    m = re.search(r"(?:-{3,}[ \t]*Bridge[ \t]*-{3,}|^[ \t]*BRIDGE[ \t]*$).*?(?=^\s*DNS[ \t]+PRIMARIO|^\s*CAPA[ \t]+2[ \t]*:|\Z)",
                  text, re.I | re.M | re.S)
    bridge = m.group(0) if m else ""
    d["bridge_ip"] = find_after("IPAddress", bridge)
    d["bridge_mask"] = find_after("SubnetMask", bridge)
    d["bridge_gw"] = find_after("X_SKYW_DefaultGateway", bridge)

    priv_dmz = find_line("IP PRIVADA 1", text, 1)
    priv_port = find_line("IP PRIVADA 1", text, 2)
    d["dmz"] = "" if d["dmzreq"].strip().upper() == "NO" else priv_dmz
    d["forward"] = "" if d["portreq"].strip().upper() == "NO" else priv_port
    d["port"] = "" if d["portreq"].strip().upper() == "NO" else find_line("PUERTO INTERNO 1", text)
    return d


def missing_fields(d: dict) -> list:
    required = ["id", "rr", "regional", "actividad", "ip", "mask", "gw"]
    if d.get("bridgereq", "").strip().upper() == "SI":
        required.append("bridge_ip")
    return [k for k in required if not d.get(k)]


def resumen(d: dict) -> list:
    """Pares (etiqueta, valor) de lo que se cargará en el formulario."""
    claves = ["id", "rr", "regional", "actividad", "propiedad", "olt", "ip", "gw", "mask", "bridge_ip", "dmz", "forward", "port"]
    return [(ETIQUETAS[k], d.get(k) or "—") for k in claves]


# ----------------------------------------------------------------------------- registro diario
def _ruta_historial():
    return data_dir() / "historial_documentacion.json"


def _cargar_registro() -> dict:
    try:
        data = json.loads(_ruta_historial().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clave_registro(d: dict) -> str:
    """La cuenta RR identifica la cuenta; el ID del caso es respaldo."""
    return str(d.get("rr", "")).strip() or str(d.get("id", "")).strip()


def documentada_hoy(d: dict, ahora: datetime = None) -> bool:
    key = clave_registro(d)
    if not key:
        return False
    dia = (ahora or datetime.now()).strftime("%Y-%m-%d")
    return any(str(i.get("key", "")).strip().upper() == key.upper() for i in _cargar_registro().get(dia, []))


def marcar_documentada(d: dict, ahora: datetime = None) -> None:
    """Se llama solo después de que Forms acepta el envío."""
    ahora = ahora or datetime.now()
    key = clave_registro(d)
    if not key:
        return
    dia = ahora.strftime("%Y-%m-%d")
    reg = _cargar_registro()
    items = reg.setdefault(dia, [])
    for it in items:
        if str(it.get("key", "")).strip().upper() == key.upper():
            it.update({"id": d.get("id", ""), "rr": d.get("rr", ""), "hora": ahora.strftime("%H:%M:%S"), "documentada": True})
            break
    else:
        items.append({"key": key, "id": d.get("id", ""), "rr": d.get("rr", ""),
                      "hora": ahora.strftime("%H:%M:%S"), "documentada": True})
    _ruta_historial().write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
