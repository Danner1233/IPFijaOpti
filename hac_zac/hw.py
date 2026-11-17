# -*- coding: utf-8 -*-
"""Lectura de salidas de equipos (Huawei/ZTE) para armar la evidencia de la plantilla.

Portado de core/parsers.py de Hendrix GPON. Se ejecuta en el proceso de la interfaz
(Python 3): el script de SecureCRT solo envia las salidas crudas.
"""
import re

def clasificar_red(tipo, nombre):
    """CLARO (HAC/ZAC propios), ATP (nombre con '.ATP') u ONNET (OH_ / ONNET). '' si no hay Capa 2."""
    up = (nombre or "").upper()
    if tipo == "OH" or up.startswith(("OH-", "OH_")) or "ONNET" in up:
        return "ONNET"
    if ".ATP" in up:
        return "ATP"
    if tipo in ("HAC", "ZAC"):
        return "CLARO"
    return ""


def obtener_fila_vlan_201(salida_service_port):
    """Fila del service-port con VLAN 201: {'index','rx','tx','linea'} o None.
    RX/TX se toman desde el final de la fila (las columnas F/S/P vienen partidas: '0/4 /13')."""
    for linea in salida_service_port.splitlines():
        partes = linea.split()
        if len(partes) < 8 or not partes[0].isdigit() or partes[1] != "201":
            continue
        return {"index": partes[0], "rx": partes[-3], "tx": partes[-2], "linea": " ".join(partes)}
    return None


def describir_tid(salida_traffic, tid):
    """'TID 140: CIR 512 kbps, PIR 704 kbps' desde la tabla de tráfico (o '')."""
    m = re.search(r"^\s*{}\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)".format(re.escape(str(tid))),
                  salida_traffic or "", re.MULTILINE)
    if not m:
        return ""
    cir, _cbs, pir, _pbs = m.groups()
    return "TID {}: CIR {} kbps, PIR {} kbps".format(tid, cir, pir)


def obtener_descripcion_ont(salida_ont):
    m = re.search(r"^\s*Description\s*:\s*(.*)$", salida_ont or "", re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


_RE_PROMPT_FINAL = re.compile(r"^\s*[<\[]?\S{1,100}(?:>|#|\])\s*$")


def limpiar_salida(texto):
    """Salida de equipo lista para pegar en la plantilla: sin ANSI, sin paginador ni prompt final."""
    t = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", (texto or "").replace("\r", ""))
    lineas = [l.rstrip() for l in t.split("\n")]
    lineas = [l for l in lineas if not re.match(r"^\s*(--\s*$|\(\s*Press 'Q' to break\s*\))", l)]
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if lineas and _RE_PROMPT_FINAL.match(lineas[-1]) and " " not in lineas[-1].strip():
        lineas.pop()
    while lineas and not lineas[0].strip():
        lineas.pop(0)
    out, vacias = [], 0
    for l in lineas:
        vacias = vacias + 1 if not l.strip() else 0
        if vacias <= 1:
            out.append(l)
    return "\n".join(out)


def fila_eth_puerto(salida, ont_id, puerto="4"):
    """Fila del puerto ETH <puerto> en la salida de 'display ont port attribute <p> <ont> eth'.

    Ej.: '35 4 ETH enable auto auto on off 201 0'. Devuelve '' si no se encuentra (quien llama
    decide qué mostrar en ese caso).
    """
    rx = re.compile(r"^\s*{}\s+{}\s+ETH\b".format(re.escape(str(ont_id)), re.escape(str(puerto))), re.IGNORECASE)
    for linea in limpiar_salida(salida).split("\n"):
        if rx.match(linea):
            return linea.strip()
    return ""


def lineas_que_coinciden(texto, patron):
    """Líneas (sin espacios sobrantes) de 'texto' que cumplen la expresión 'patron'."""
    rx = re.compile(patron, re.IGNORECASE)
    return [l.strip() for l in (texto or "").replace("\r", "").split("\n") if rx.search(l)]
