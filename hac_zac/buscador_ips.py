# -*- coding: utf-8 -*-
"""Buscador de IPs por NODO (para cuando el Hendrix / jump host no responde).

Se alimenta del Excel "Buscador IPs por Nodo" (historico de solicitudes de la lista de SharePoint). Igual que su
tabla dinamica: solo solicitudes EXITOSAS, agrupadas por NODO_FINAL -> Puerta de enlace usada, con las IPs que ya
se asignaron en esa puerta de enlace (para no repetir una).

* Se lee el .xlsx directamente (zip + XML, por partes): no necesita openpyxl (el Python del instalador no lo trae).
* Del Excel SOLO se guardan nodo, puerta de enlace, IPs asignadas, fecha, red, OLT y VLAN. NO se guardan nombres,
  direcciones, correos ni cuentas de clientes.
* El indice queda en <carpeta del equipo>/buscador_ips.json (lo comparten todos; quien actualiza el Excel lo
  actualiza para todos) y, sin carpeta, en los datos locales.
"""
import json
import os
import re
import zipfile
from datetime import datetime, timedelta
from xml.etree.ElementTree import iterparse

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
ARCHIVO = "buscador_ips.json"

COLUMNAS = {                     # clave interna: encabezado en el Excel
    "tipo": "Tipo Reporte Resultado Actividad",
    "ip": "IP Asignada",
    "gw": "Puerta Enlace",
    "fecha": "Creado",
    "nodo": "ID CASO:NODO_FINAL",
    "red": "PROPIEDA_RED",
    "olt": "OLT_ATP",
    "vlan": "UVLAN",
    "regional": "Regional",
}
_IP = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class ErrorExcel(Exception):
    pass


# ---------------------------------------------------------------------------------------------- leer el xlsx
def _col(ref):
    """'AB12' -> 27 (base 0)."""
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _compartidas(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out = []
    with z.open("xl/sharedStrings.xml") as f:
        for ev, el in iterparse(f, events=("end",)):
            if el.tag == NS + "si":
                out.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    return out


def _primera_hoja(z):
    """Ruta de la primera hoja del libro (la de datos)."""
    import xml.etree.ElementTree as ET
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    hoja = wb.find(NS + "sheets/" + NS + "sheet")
    if hoja is None:
        raise ErrorExcel("El Excel no tiene hojas.")
    rid = hoja.get(NS_R + "id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for r in rels:
        if r.get("Id") == rid:
            destino = r.get("Target").lstrip("/")
            return destino if destino.startswith("xl/") else "xl/" + destino
    return "xl/worksheets/sheet1.xml"


def filas_xlsx(ruta):
    """Genera cada fila de la primera hoja como lista de textos (sin openpyxl, por partes)."""
    try:
        z = zipfile.ZipFile(ruta)
    except (zipfile.BadZipFile, OSError) as e:
        raise ErrorExcel("No se pudo abrir el Excel: %s" % e)
    with z:
        comp = _compartidas(z)
        with z.open(_primera_hoja(z)) as f:
            for ev, el in iterparse(f, events=("end",)):
                if el.tag != NS + "row":
                    continue
                fila = []
                for c in el.iter(NS + "c"):
                    i = _col(c.get("r") or "")
                    t = c.get("t")
                    if t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(NS + "t"))
                    else:
                        v = c.find(NS + "v")
                        val = v.text if v is not None and v.text is not None else ""
                        if t == "s" and val:
                            val = comp[int(val)]
                    if i >= len(fila):
                        fila.extend([""] * (i + 1 - len(fila)))
                    fila[i] = val
                yield fila
                el.clear()


def _fecha(v):
    """Numero de serie de Excel o texto ISO -> 'AAAA-MM-DD'."""
    v = str(v or "").strip()
    if not v:
        return ""
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d")
    except ValueError:
        return v[:10]


def _ip_orden(ip):
    try:
        return tuple(int(x) for x in ip.split("."))
    except ValueError:
        return (999,)


# ---------------------------------------------------------------------------------------------- indice
def construir(filas, progreso=None):
    """De las filas del Excel (la primera es el encabezado) arma el indice por nodo."""
    it = iter(filas)
    try:
        cab = [str(c or "").strip() for c in next(it)]
    except StopIteration:
        raise ErrorExcel("El Excel esta vacio.")
    pos = {}
    for k, nombre in COLUMNAS.items():
        if nombre in cab:
            pos[k] = cab.index(nombre)
    faltan = [COLUMNAS[k] for k in ("tipo", "gw", "nodo") if k not in pos]
    if faltan:
        raise ErrorExcel("Al Excel le faltan las columnas: %s" % ", ".join(faltan))

    def val(fila, k):
        i = pos.get(k)
        return str(fila[i]).strip() if i is not None and i < len(fila) and fila[i] is not None else ""

    nodos, leidas, usadas = {}, 0, 0
    for fila in it:
        leidas += 1
        if progreso and leidas % 2000 == 0:
            progreso(leidas)
        if val(fila, "tipo").lower() != "exitosa":
            continue
        nodo, gw = val(fila, "nodo").upper(), val(fila, "gw")
        if not nodo or not _IP.match(gw):
            continue
        usadas += 1
        g = nodos.setdefault(nodo, {}).setdefault(gw, {"n": 0, "ultima": "", "ips": set(), "red": "", "olt": "",
                                                       "vlan": "", "regional": ""})
        g["n"] += 1
        ip = val(fila, "ip")
        if _IP.match(ip):
            g["ips"].add(ip)
        f = _fecha(val(fila, "fecha"))
        if f >= g["ultima"]:
            g["ultima"] = f
            for k in ("red", "olt", "vlan", "regional"):
                g[k] = val(fila, k) or g[k]
    for gws in nodos.values():
        for g in gws.values():
            g["ips"] = sorted(g["ips"], key=_ip_orden)
    return {"filas": leidas, "exitosas": usadas, "nodos": nodos}


def ruta_indice(carpeta_equipo=""):
    if carpeta_equipo:
        return os.path.join(carpeta_equipo, ARCHIVO)
    from .rutas import data_dir
    return str(data_dir() / ARCHIVO)


def importar(ruta_xlsx, carpeta_equipo="", progreso=None, ahora=None):
    """Lee el Excel, arma el indice y lo guarda. Devuelve el indice."""
    ind = construir(filas_xlsx(ruta_xlsx), progreso)
    if not ind["nodos"]:
        raise ErrorExcel("No se encontro ninguna solicitud Exitosa con nodo y puerta de enlace.")
    ind.update(importado=(ahora or datetime.now()).isoformat(timespec="seconds"),
               origen=os.path.basename(ruta_xlsx))
    destino = ruta_indice(carpeta_equipo)
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    tmp = destino + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ind, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, destino)
    return ind


def cargar(carpeta_equipo=""):
    """El indice de la carpeta del equipo (o el local). {} si no hay."""
    for r in ([ruta_indice(carpeta_equipo)] if carpeta_equipo else []) + [ruta_indice("")]:
        try:
            with open(r, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}


def buscar(indice, texto, maximo=50):
    """Filas [{nodo, gw, n, ultima, red, olt, vlan, regional, ips}] de los nodos que coinciden con `texto`:
    primero el nodo exacto, luego los que empiezan asi y luego los que lo contienen. Dentro de cada nodo, la puerta
    de enlace mas usada primero."""
    t = str(texto or "").strip().upper()
    if not t:
        return []
    nodos = (indice or {}).get("nodos") or {}
    exactos = [n for n in nodos if n == t]
    empiezan = sorted(n for n in nodos if n != t and n.startswith(t))
    contienen = sorted(n for n in nodos if t in n and not n.startswith(t))
    out = []
    for n in (exactos + empiezan + contienen)[:maximo]:
        for gw, g in sorted(nodos[n].items(), key=lambda kv: (-kv[1]["n"], _ip_orden(kv[0]))):
            out.append(dict(g, nodo=n, gw=gw))
    return out
