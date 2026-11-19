"""Generación de la plantilla de configuración (.txt) y de los textos de casos bridge.

Las plantillas base viven en la carpeta de datos\\ (plantilla_base.txt y plantilla_caso_bridge.txt):
se crean la primera vez y se pueden editar. Los marcadores son {{NOMBRE}}.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .rutas import data_dir

SEPARADOR = "-" * 44

# CÓDIGO de servicio -> megas (tabla del operador). El código manda sobre el número que venga escrito.
CODIGO_MEGAS = {
    "I1P": 30, "I2P": 45, "I3P": 50, "I4P": 75, "I5P": 80, "I6P": 100, "I7P": 150, "I8P": 200,
    "I2E": 200, "I2F": 250, "I9P": 300, "I3F": 350, "I3E": 350, "I4F": 450, "I4E": 450, "D4B": 500,
    "I5F": 550, "I5E": 550, "I6E": 550, "I9F": 950,
}


def megas_por_codigo(codigo: str) -> str:
    return str(CODIGO_MEGAS.get((codigo or "").strip().upper(), "")) 


ENCABEZADO_VACIO = """  --- DATOS DE CONFIGURACIÓN ---
 
CONFIGURADOR: {{CONFIGURADOR}}
 
 ++++++SOLICITUD ID: {{SOLICITUD_ID}}++++++


TIPO SOLICITUD CONFIG:

PROPIEDAD RED: 


SERVICIO SOBRE ATP:

NAP ATP:

DIRECCIÓN CLIENTE:

ID HANDLE:

ID RESERVA ATP:

ID SERVICIO ATP:


SERVICIO SOBRE ONNET:
NAP ONNET:
DIRECCIÓN CLIENTE:
PLACE ID:
ID RESERVA ONNET:
ID SERVICIO ONNET:


NODO: 

CUENTA RR: {{RR}}
OT/LLs RR: 
NOMBRE CLIENTE: 
REGIONAL: 
CIUDAD: 
CÓDIGO SERVICIO: 
SERIAL ONT: 
MAC ONT:
ANCHO DE BANDA: 
NOMBRE TÉCNICO: 
CELULAR TÉCNICO: 

ALIADO: 
TIPO ACTIVIDAD: 
REQUIERE IP BRIDGE? 
REQUIERE DMZ? 
IP PRIVADA 1:
REQUIERE PORT FW? 
IP PRIVADA 1:
PUERTO INTERNO 1:
PUERTO EXTERNO 1:


CANTIDAD DE IPs A CONFIGURAR:




FECHA SOLICITUD:"""

CUERPO_BASE = """ 
""" + SEPARADOR + """
""" + SEPARADOR + """
 
©©©©©  SWITCH ©©©©©
 
 
* PREVIA-CONFIGURACIÓN:
{{SWITCH_PREVIA}}
 
 
* CONFIGURADO:
{{SWITCH_CONFIG}}
 
 
©©©©©© VELOCIDAD ASIGNADA ©©©©©©
 
* PREVIA-CONFIGURACIÓN:
{{VELOCIDAD_PREVIA}}
 
 
* CONFIGURADO:
{{VELOCIDAD_CONFIG}}


©©©©©© BRIDGE ©©©©©©


* PREVIA-CONFIGURACIÓN:
{{BRIDGE_PREVIA}}
 
 
* CONFIGURADO:
{{BRIDGE_CONFIG}}
 

 
©©©©©© VALIDACIONES L2 ©©©©©©
{{VALIDACION_L2}}
 
©©©©©© VALIDACIONES ADICIONALES ©©©©©©
 
1. Búsqueda de L2 en E-management
 
 
2. Búsqueda segmento de red en CRT:
 
{{DIS_CUR_INT}}
 
©©©©©© CONFIGURACIÓN CPE   ©©©©©©
 
--- ACS CLIENT INFORMATION ---
 
{{ACS}}
 
--- DEVICE  STATUS ---
 
 
--- CONFIG WAN ---
 
 
--- CONFIGURACIONES AVANZADAS ---
 
¿Cuales?
 
*
*
* 
REPORTE ACTIVIDAD:
N° De Visita:1
Actividad Finalizada: si
Escalamiento Técnico Realizado: NO
Requiere nueva visita:     NO
Motivo Reagendamiento:  NO
 
©©©©©© MARCACIÓN IP / NETCRACKER ©©©©©©
 
{{MARCACION}}
 
©©©©©© DIRECCIONAMIENTO FINAL ©©©©©©
 
Solicitud ID: {{SOLICITUD_ID}}
Cuenta RR: {{RR}}
 
IPAddress:
{{IP}}
SubnetMask:
{{MASCARA}}
X_SKYW_DefaultGateway:
{{GATEWAY}}


CAPA 2:
{{CAPA2}}

Navegación Internet: OK?
Ancho de Banda: OK?
Funcionamiento IP Fija: OK?
Funcionamiento IP Bridge: OK?

-------Bridge--------


IPAddress:
{{IP_BRIDGE}}
SubnetMask:
{{MASCARA_BRIDGE}}
X_SKYW_DefaultGateway:
{{GATEWAY_BRIDGE}}

 
 
DNS PRIMARIO
190.157.8.42
DNS SECUNDARIO
190.157.8.46


Ping:
{{PING}}
"""

CASO_BRIDGE_BASE = """Cuenta RR: {{RR}}
OT: {{OT}}
ProductId: {{PRODUCT_ID}}
Serial number : {{SERIAL}}
Product class:  {{PRODUCT_CLASS}}
CAPA2 : {{CAPA2}}
IP: {{IP_BRIDGE}}
"""

TITULO_CASO_BRIDGE = "CTA-RR/{rr}/CONFIGURACIÓN MODO BRIDGE"


# ----------------------------------------------------------------------------- utilidades
_ESPACIOS_RAROS = dict.fromkeys(map(ord, "     　"), " ")
_SIN_ANCHO = dict.fromkeys(map(ord, "​‌‍﻿"), None)


def _norm(texto: str) -> str:
    """Saltos de linea uniformes y sin espacios "duros" ni invisibles (Outlook web los usa en algunos correos)."""
    t = (texto or "").replace("\r\n", "\n").replace("\r", "\n")
    return t.translate(_ESPACIOS_RAROS).translate(_SIN_ANCHO)


def render(plantilla: str, valores: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(valores.get(m.group(1), "") or ""), plantilla)


def _leer_plantilla(nombre: str, defecto: str, requeridos=()) -> str:
    """Lee la plantilla editable del usuario. Si es de una versión anterior (le faltan marcadores nuevos)
    se respalda como .bak y se reemplaza por la versión actual."""
    ruta = data_dir() / nombre
    try:
        texto = _norm(ruta.read_text(encoding="utf-8"))
        if all(r in texto for r in requeridos):
            return texto
        ruta.replace(ruta.with_suffix(".bak"))
    except Exception:
        pass
    ruta.write_text(defecto, encoding="utf-8")
    return defecto


# ----------------------------------------------------------------------------- análisis de lo pegado
def _buscar(texto: str, patron: str) -> str:
    m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def extraer_solicitud(texto: str) -> str:
    """Devuelve solo la solicitud: desde '++++SOLICITUD ID: n++++' hasta la linea 'FECHA SOLICITUD:'.
    Quita lo que rodea (encabezados del correo, 'DATOS DE CONFIGURACION', firmas, etc.).
    Si no encuentra el inicio, devuelve el texto tal cual (sin espacios sobrantes)."""
    t = _norm(texto)
    ini = re.search(r"^[ \t]*\+*[ \t]*SOLICITUD\s*ID\s*:", t, re.M | re.I)
    if not ini:
        return t.strip()
    t = t[ini.start():]
    fin = re.search(r"^[ \t]*FECHA SOLICITUD:[^\n]*", t, re.M | re.I)
    if fin:
        t = t[:fin.end()]
    return "\n".join(l.rstrip() for l in t.strip().split("\n"))


def es_fila_sp(texto: str) -> bool:
    """¿Es una fila copiada de la lista de SharePoint (columnas separadas por tabulador)?"""
    t = texto or ""
    return t.count("\t") >= 8 and re.match(r"\s*\d{4,7}\t", t) is not None


def desde_fila_sp(texto: str) -> str:
    """Convierte una fila pegada de SharePoint a la plantilla de siempre (SOLICITUD ID, CUENTA RR, ...).
    Reconoce cada dato por su forma (no por la posición), así sirve aunque cambien columnas vacías."""
    from . import cola
    cel = [c.strip() for c in (texto or "").strip("\r\n").split("\t")]
    lleno = [c for c in cel if c]
    d = {"id": cel[0]}

    def primero(pat, desde=0, flags=re.I):
        for i in range(desde, len(cel)):
            if re.fullmatch(pat, cel[i], flags):
                return i
        return -1

    i = primero(r"ONNET|ATP|CLARO|OH|ON-?NET")
    d["propiedad_red"] = cel[i].upper() if i >= 0 else ""
    i = primero(r"(INC|OT|LL)\w*\d{5,}")
    d["ot"] = cel[i] if i >= 0 else ""
    irr = primero(r"\d{1,3}(\.\d{3}){1,3}")
    if irr >= 0:
        d["rr"] = cel[irr].replace(".", "")
        j = irr + 1
        while j < len(cel) and not cel[j]:
            j += 1
        d["cliente"] = cel[j] if j < len(cel) else ""
        k = j + 1
        while k < len(cel) and not cel[k]:
            k += 1
        if k < len(cel) and re.fullmatch(r"\d{7,10}", cel[k]):     # OT/LLs RR: el número que sigue al cliente
            d["ot"] = cel[k]
    imac = primero(r"([0-9A-F]{2}[:\-.]){5}[0-9A-F]{2}")
    if imac < 0:      # 12 hex seguidos (sin separadores): debe traer letras para no confundirlo con un número
        for k, c in enumerate(cel):
            if re.fullmatch(r"[0-9A-F]{12}", c, re.I) and re.search(r"[A-F]", c, re.I) and re.search(r"\d", c):
                imac = k
                break
    d["mac"] = cel[imac] if imac >= 0 else ""
    i = primero(r"(ZTE|SEI|SDM|SERC|SKY|HWTC|FHTT|ALCL|GPON|CIGG|HWT)[0-9A-Z]{6,14}")
    if i < 0:
        i = primero(r"[A-Z]{3,5}[0-9A-F]{8}")
    d["serial"] = cel[i] if i >= 0 else ""
    # Después del equipo (MAC o, si la fila trae SERIAL en vez de MAC, el serial), en orden: regional, ciudad,
    # aliado, ¿activ. apoyo?, ¿bridge?, tipo de actividad, código, megas, técnico, celular, ¿DMZ?
    # (se leen los datos con valor, en ese orden)
    ancla = imac if imac >= 0 else i
    if ancla >= 0:
        seq = [c for c in cel[ancla + 1:] if c]
        for clave, v in zip(("regional", "ciudad", "aliado"), seq[:3]):
            d[clave] = v
        r = seq[3:]
        if len(r) >= 3 and re.fullmatch(r"S[IÍ]|NO", r[0], re.I) and re.fullmatch(r"S[IÍ]|NO", r[1], re.I):
            d["bridge"] = r[1].upper().replace("Í", "I")
            d["tipo_actividad"] = r[2]                     # tal cual viene (Brownfield, Instalación Nueva...)
            r = r[3:]
        # código de servicio: el primero que esté en la tabla (o con forma I2F / D4B)
        cod = next((c.upper() for c in r if c.upper() in CODIGO_MEGAS), "") or \
            next((c.upper() for c in r if re.fullmatch(r"[A-Z]\d[A-Z]", c, re.I)), "")
        d["codigo"] = cod
        d["megas"] = megas_por_codigo(cod) or next((c for c in r if re.fullmatch(r"\d{2,4}", c)), "")
        k = r.index(d["megas"]) if d["megas"] in r else (r.index(cod) if cod in [x.upper() for x in r] else -1)
        for c in r[k + 1:]:
            if c and not re.fullmatch(r"[\d\s+]+", c) and not d.get("tecnico"):
                d["tecnico"] = c
            if re.fullmatch(r"3\d{9}", c):
                d["celular_tecnico"] = c
                break
        if d.get("celular_tecnico") in r:
            ic = r.index(d["celular_tecnico"])
            if ic + 1 < len(r) and re.fullmatch(r"S[IÍ]|NO", r[ic + 1], re.I):
                d["dmz"] = r[ic + 1].upper().replace("Í", "I")
    return cola._texto_plantilla(d)


def parsear_solicitud(texto: str) -> dict:
    """Extrae los datos útiles del bloque 'DATOS DE CONFIGURACIÓN' pegado (o de una fila de SharePoint)."""
    if es_fila_sp(texto):
        texto = desde_fila_sp(texto)
    t = _norm(texto)
    bridge_txt = _buscar(t, r"REQUIERE IP BRIDGE\?[ \t]*(\S*)")
    return {
        # tolerante: "SOLICITUD ID: 64888", "SOLICITUD  ID :64888", o el numero en la linea/celda siguiente
        "solicitud_id": _buscar(t, r"SOLICITUD\s*ID\s*:?\s*(\d{3,})"),
        "propiedad_red": _buscar(t, r"PROPIEDAD RED:[ \t]*(.*)").upper(),
        "rr": _buscar(t, r"CUENTA RR\s*:?\s*(\d+)"),
        "ot": _buscar(t, r"OT/LLs RR:[ \t]*(\S+)"),
        "cliente": _buscar(t, r"NOMBRE CLIENTE:[ \t]*(.*)"),
        "regional": _buscar(t, r"^[ \t]*REGIONAL:[ \t]*(.*)"),
        "aliado": _buscar(t, r"^[ \t]*ALIADO:[ \t]*(.*)"),
        "serial_ont": _buscar(t, r"SERIAL ONT:[ \t]*(.*)"),
        "mac_ont": _buscar(t, r"MAC ONT:[ \t]*(\S*)"),
        "codigo": _buscar(t, r"C[ÓO]DIGO SERVICIO:[ \t]*(\S+)").upper(),
        "ancho_banda": megas_por_codigo(_buscar(t, r"C[ÓO]DIGO SERVICIO:[ \t]*(\S+)")) or _buscar(t, r"ANCHO DE BANDA:[ \t]*(\d+)"),
        "bridge": (bridge_txt.upper().startswith("S") if bridge_txt else None),
        "id_servicio_onnet": _buscar(t, r"ID SERVICIO ONNET:[ \t]*(\S+)"),
        "id_servicio_atp": _buscar(t, r"ID SERVICIO ATP:[ \t]*(\S+)"),
        "id_reserva_onnet": _buscar(t, r"ID RESERVA ONNET:[ \t]*(\S+)"),
        "id_reserva_atp": _buscar(t, r"ID RESERVA ATP:[ \t]*(\S+)"),
    }


def descripcion_cliente(nombre, rr):
    """Nombre que el script le pone a la ONT/service-port: NOMBRE en mayusculas, sin tildes, espacios por '_' y la
    cuenta RR al final. Ej.: 'Danner Arias', 1232131 -> 'DANNER_ARIAS_1232131'. '' si falta el nombre."""
    import unicodedata
    n = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode("ascii").strip().upper()
    n = re.sub(r"_+", "_", re.sub(r"\s+", "_", n)).strip("_")
    r = re.sub(r"\D", "", str(rr or "").split(".")[0])
    if not n:
        return ""
    return "%s_%s" % (n, r) if r else n


def con_bridge(descripcion):
    """La descripcion para una cuenta con IP bridge."""
    return "%s_BRIDGE" % descripcion if descripcion else ""


def datos_reporte(texto_solicitud):
    """Lo que se pide para reportar una falla, sacado de la solicitud:
    RR: 64767642 / REGIONAL: Occidente / ALIADO: CONECTAR."""
    s = parsear_solicitud(texto_solicitud or "")
    return "RR: %s\nREGIONAL: %s\nALIADO: %s" % (s.get("rr") or "", s.get("regional") or "", s.get("aliado") or "")


def parsear_acs(texto: str) -> dict:
    t = _norm(texto)
    return {
        "cliente": _buscar(t, r"User name:[ \t]*(.*)"),
        "ubicacion": _buscar(t, r"User location:[ \t]*(.*)"),
        "rr": _buscar(t, r"mycust04:[ \t]*(\d+)"),
        "serial": _buscar(t, r"Serial number:[ \t]*(\S+)"),
        "fabricante": _buscar(t, r"Manufacturer:[ \t]*(.*)"),
        "oui": _buscar(t, r"Manufacturer OUI:[ \t]*(\S+)"),
        "product_class": _buscar(t, r"Product class:[ \t]*(\S+)"),
        "hw": _buscar(t, r"Hardware version:[ \t]*(.*)"),
        "fw": _buscar(t, r"Firmware version:[ \t]*(.*)"),
        "ip": _buscar(t, r"IP address:[ \t]*(\d{1,3}(?:\.\d{1,3}){3})"),
    }


def normalizar_sn(serial: str) -> str:
    """SN para los equipos: sin ':' ni separadores, en mayúsculas."""
    return re.sub(r"[^A-Za-z0-9]", "", serial or "").upper()


# ----------------------------------------------------------------------------- armado
@dataclass
class DatosPlantilla:
    configurador: str = ""
    solicitud: str = ""          # bloque pegado (o vacío)
    acs: str = ""                # bloque ACS pegado
    dis_cur_int: str = ""
    capa2: str = ""
    capa2_ip: str = ""          # IP del Capa 2: va al lado del nombre en DIRECCIONAMIENTO FINAL
    rr: str = ""
    ip: str = ""
    mascara: str = ""
    gateway: str = ""
    ip_bridge: str = ""
    mascara_bridge: str = ""
    gateway_bridge: str = ""
    prefijo: Optional[int] = None
    validacion_l2: str = ""
    solicitud_id: str = ""
    switch_previa: str = ""
    switch_config: str = ""
    velocidad_previa: str = ""
    velocidad_config: str = ""
    bridge_previa: str = ""
    bridge_config: str = ""
    ping: str = ""              # diagnóstico IPPing pegado (va al final, bajo «Ping:»)


def _encabezado(d: DatosPlantilla) -> str:
    t = _norm(d.solicitud).strip("\n")
    if t.strip():
        corte = re.search(r"^\s*-{10,}\s*$|©©©©©\s+SWITCH", t, re.MULTILINE)   # por si pegaron la plantilla entera
        if corte:
            t = t[:corte.start()].rstrip()
        if not re.search(r"DATOS DE CONFIGURACI", t, re.IGNORECASE):
            t = "  --- DATOS DE CONFIGURACIÓN ---\n \n" + t
        if re.search(r"^\s*CONFIGURADOR:.*$", t, re.IGNORECASE | re.MULTILINE):
            t = re.sub(r"^(\s*CONFIGURADOR:).*$", lambda m: m.group(1) + " " + d.configurador, t,
                       count=1, flags=re.IGNORECASE | re.MULTILINE)
        else:
            t = re.sub(r"(DATOS DE CONFIGURACI[^\n]*\n)", lambda m: m.group(1) + " \nCONFIGURADOR: " + d.configurador + "\n",
                       t, count=1, flags=re.IGNORECASE)
        return t
    return render(ENCABEZADO_VACIO, {"CONFIGURADOR": d.configurador, "SOLICITUD_ID": d.solicitud_id, "RR": d.rr})


def _marcacion(d: DatosPlantilla) -> str:
    if not d.ip:
        return ""
    p = "/{}".format(d.prefijo) if d.prefijo else ""
    tabs = "\t" * 7
    lineas = ["\t{}{}{}Assigned\t{}".format(d.ip, p, tabs, d.rr)]
    if d.ip_bridge:
        lineas.append("\t{}{}{}Assigned\t{} BRIDGE".format(d.ip_bridge, p, tabs, d.rr))
    return "\n".join(lineas)


DNS_PRIMARIO = "190.157.8.42"
DNS_SECUNDARIO = "190.157.8.46"


def construir_direccionamiento(d: DatosPlantilla) -> str:
    """Bloque «DIRECCIONAMIENTO FINAL» listo para pegar (con o sin bridge)."""
    def bloque(ip, mascara, gateway):
        return "IPAddress:\n{}\nSubnetMask:\n{}\nX_SKYW_DefaultGateway:\n{}".format(ip, mascara, gateway)

    cab = "©©©©©© DIRECCIONAMIENTO FINAL ©©©©©©\n \nSolicitud ID: {}\nCuenta RR: {}\n \n".format(d.solicitud_id, d.rr)
    dns = "DNS PRIMARIO\n{}\nDNS SECUNDARIO\n{}".format(DNS_PRIMARIO, DNS_SECUNDARIO)
    capa2 = "CAPA 2:\n{}".format(_capa2_con_ip(d))
    ok = ("Navegación Internet: OK?\nAncho de Banda: OK?\nFuncionamiento IP Fija: OK?\n"
          "Funcionamiento IP Bridge: OK?")
    if d.ip_bridge:
        cuerpo = (bloque(d.ip, d.mascara, d.gateway) + "\n\n-------Bridge--------\n\n\n" +
                  bloque(d.ip_bridge, d.mascara_bridge or d.mascara, d.gateway_bridge or d.gateway) +
                  "\n\n \n \n" + dns + "\n\n" + capa2 + "\n\n\n" + ok)
    else:
        cuerpo = bloque(d.ip, d.mascara, d.gateway) + "\n\n\n" + capa2 + "\n\n" + dns + "\n\n" + ok
    return cab + cuerpo + "\n"


def _acs_sin_titulo(acs: str) -> str:
    t = _norm(acs).strip("\n")
    return re.sub(r"^\s*-+\s*ACS CLIENT INFORMATION\s*-+\s*\n?", "", t, flags=re.IGNORECASE).strip("\n")


SEP_CAPA2_IP = " - "     # «NOMBRE - IP»; core/documentacion.py quita esta IP al leer el campo OLT del formulario


def _capa2_con_ip(d: DatosPlantilla) -> str:
    nombre, ip = (d.capa2 or "").strip(), (d.capa2_ip or "").strip()
    return nombre + SEP_CAPA2_IP + ip if nombre and ip else nombre


def _ping_limpio(ping: str) -> str:
    """Texto del ping tal como se pegó (sin líneas vacías al inicio/final ni espacios sobrantes a la derecha)."""
    lineas = [l.rstrip() for l in _norm(ping).split("\n")]
    while lineas and not lineas[0].strip():
        lineas.pop(0)
    while lineas and not lineas[-1].strip():
        lineas.pop()
    return "\n".join(lineas)


def _con_marcador_ping(plantilla: str) -> str:
    """Si la plantilla editable del usuario es anterior y no trae {{PING}}, lo agrega bajo el último «Ping:»
    (o al final). Así no hace falta reemplazar ni perder lo que el usuario haya personalizado."""
    if "{{PING}}" in plantilla:
        return plantilla
    ms = list(re.finditer(r"^[ \t]*Ping:[ \t]*$", plantilla, re.IGNORECASE | re.MULTILINE))
    if ms:
        fin = ms[-1].end()
        return plantilla[:fin] + "\n{{PING}}" + plantilla[fin:]
    return plantilla.rstrip() + "\n\nPing:\n{{PING}}\n"


def construir_plantilla(d: DatosPlantilla) -> str:
    base = _leer_plantilla("plantilla_base.txt", CUERPO_BASE,
                           ("{{SWITCH_CONFIG}}", "{{VELOCIDAD_CONFIG}}", "{{BRIDGE_CONFIG}}", "{{SOLICITUD_ID}}"))
    cuerpo = render(_con_marcador_ping(base), {
        "SOLICITUD_ID": d.solicitud_id,
        "SWITCH_PREVIA": d.switch_previa, "SWITCH_CONFIG": d.switch_config,
        "VELOCIDAD_PREVIA": d.velocidad_previa, "VELOCIDAD_CONFIG": d.velocidad_config,
        "BRIDGE_PREVIA": d.bridge_previa, "BRIDGE_CONFIG": d.bridge_config,
        "VALIDACION_L2": d.validacion_l2, "DIS_CUR_INT": _norm(d.dis_cur_int).strip("\n"),
        "ACS": _acs_sin_titulo(d.acs), "MARCACION": _marcacion(d), "RR": d.rr, "IP": d.ip,
        "MASCARA": d.mascara, "GATEWAY": d.gateway, "CAPA2": _capa2_con_ip(d), "IP_BRIDGE": d.ip_bridge,
        "MASCARA_BRIDGE": d.mascara_bridge, "GATEWAY_BRIDGE": d.gateway_bridge, "PING": _ping_limpio(d.ping)})
    texto = _encabezado(d).rstrip() + "\n" + cuerpo
    return texto.rstrip() + "\n"


def titulo_caso_bridge(rr: str) -> str:
    return TITULO_CASO_BRIDGE.format(rr=rr or "XXXXX")


def construir_caso_bridge(rr, ot, product_id, serial, product_class, capa2, ip_bridge) -> str:
    return render(_leer_plantilla("plantilla_caso_bridge.txt", CASO_BRIDGE_BASE), {
        "RR": rr, "OT": ot, "PRODUCT_ID": product_id, "SERIAL": serial,
        "PRODUCT_CLASS": product_class, "CAPA2": capa2, "IP_BRIDGE": ip_bridge}).rstrip() + "\n"


# ----------------------------------------------------------------------------- archivos
def _limpio(texto: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_\-]+", "_", (texto or "").strip())
    return re.sub(r"_+", "_", t).strip("_")


def carpeta_base(configurada: str) -> Path:
    return Path(configurada) if configurada else Path.home() / "Documents" / "Plantillas Hendrix"


def nombre_estandar(rr: str, cliente: str) -> str:
    """<RR>_<CLIENTE> (sin extensión)."""
    return "{}_{}".format(_limpio(rr) or "SIN_RR", _limpio(cliente) or "SIN_NOMBRE")


def _carpeta_fecha(base: str, formato_carpeta: str, ahora: datetime = None) -> Path:
    ahora = ahora or datetime.now()
    if formato_carpeta == "-":
        return carpeta_base(base)
    try:
        sub = ahora.strftime(formato_carpeta or "%m-%d")
    except ValueError:
        sub = ahora.strftime("%m-%d")
    return carpeta_base(base) / _limpio(sub)


def ruta_destino(base: str, formato_carpeta: str, rr: str, cliente: str, ahora: datetime = None) -> Path:
    """<base>/<MM-DD>/<RR>_<CLIENTE>.txt; si existe, agrega _2, _3…"""
    carpeta = _carpeta_fecha(base, formato_carpeta, ahora)
    nombre = nombre_estandar(rr, cliente)
    ruta = carpeta / (nombre + ".txt")
    n = 2
    while ruta.exists():
        ruta = carpeta / "{}_{}.txt".format(nombre, n)
        n += 1
    return ruta


def ruta_con_nombre(base: str, formato_carpeta: str, nombre: str, ahora: datetime = None) -> Path:
    """<base>/<MM-DD>/<nombre elegido>.txt (misma carpeta de fecha que el estándar). No agrega sufijos:
    si ya existe, quien llama decide si lo reemplaza."""
    limpio = _limpio(re.sub(r"\.txt$", "", (nombre or "").strip(), flags=re.IGNORECASE))
    if not limpio:
        raise ValueError("El nombre no puede quedar vacío (use letras, números, guion o guion bajo).")
    return _carpeta_fecha(base, formato_carpeta, ahora) / (limpio + ".txt")


def guardar(texto: str, ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def _normal(t: str) -> str:
    return "\n".join(x.rstrip() for x in (t or "").replace("\r", "").split("\n")).strip()


def esta_guardada(texto: str, ruta) -> bool:
    """True si el .txt existe y tiene la plantilla tal como se ve (puede traer al final el caso TCO/INCLA que se
    agrega aparte). Plantilla vacia = nada que guardar."""
    actual = _normal(texto)
    if not actual:
        return True
    if not ruta:
        return False
    try:
        with open(str(ruta), encoding="utf-8", newline="") as f:     # sin traducir saltos: lo hace _normal
            en_disco = _normal(f.read())
    except (OSError, UnicodeDecodeError):
        return False
    return en_disco == actual or en_disco.startswith(actual + "\n")


def agregar_caso(ruta: Path, numero_caso: str, descripcion: str = "") -> None:
    """Agrega al final del .txt el número de caso (TCO/INCLA) y, si hay, la descripción del bridge."""
    extra = "\n \n{}\n".format(numero_caso.strip())
    if descripcion.strip():
        extra += " \n" + descripcion.rstrip() + "\n"
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(extra)
