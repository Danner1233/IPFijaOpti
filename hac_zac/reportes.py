# -*- coding: utf-8 -*-
"""Registro y reporte del equipo en la carpeta compartida (OneDrive), para abrir en Excel.

<carpeta_equipo>/reportes/<PEM>/<AAAA-MM>/Solicitudes.csv · Pausas.csv · Conexion.csv · Horas extra.csv

* Una carpeta POR PEM (y dentro una por mes): cada PC solo escribe la suya, asi OneDrive no crea copias en
  conflicto. Los archivos del formato anterior (todos sueltos en reportes/) se mueven solos (migrar).
* CSV con ';' y UTF-8 con BOM: Excel en espanol lo abre con columnas y tildes bien.
* Si la carpeta no esta disponible, la fila queda en los datos locales (reportes_pendientes.json) y se escribe
  en la siguiente oportunidad: no se pierde nada.
* resumen_dia(): lo que muestra la pestana Reportes del admin (une los archivos de todos).
Sin datos de clientes (solo solicitud, cuenta RR, red, resultado y causa).
"""
import csv
import io
import os
import re
from datetime import datetime, timedelta

SEP = ";"
COLUMNAS = {
    "pausas": ("PEM", "Fecha", "Inicio", "Fin", "Minutos reales", "Minutos elegidos", "Razón", "Cómo terminó"),
    "conexion": ("PEM", "Fecha", "Desde", "Hasta", "Estado", "Minutos"),
    "solicitudes": ("PEM", "Fecha", "Solicitud", "Cuenta RR", "Red", "Origen", "Asignada", "Cerrada", "Minutos",
                    "Límite", "Superó el tiempo", "Resultado", "Causa", "Observación", "Justificación demora",
                    "Registro"),
    "horas_extra": ("PEM", "Fecha", "Turno", "Fin del turno", "Inicio", "Fin", "Minutos", "Tipo", "Motivo",
                    "Cómo terminó"),
}
ESTADOS = {"en_linea": "Activo", "ausente": "Ausente", "pausa": "En pausa"}
REANUDO, SE_CUMPLIO = "Reanudó", "Se cumplió el tiempo"


# ---------------------------------------------------------------------------------------------- formato
def _dt(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def fecha(d):
    return d.strftime("%d/%m/%Y")


def hora(d):
    return d.strftime("%H:%M")


def minutos(desde, hasta):
    """Minutos con un decimal y coma (Excel en espanol)."""
    m = max(0.0, (hasta - desde).total_seconds() / 60.0)
    return ("%.1f" % m).replace(".", ",")


def _num(t):
    try:
        return float(str(t or "0").replace(",", "."))
    except ValueError:
        return 0.0


def carpeta(carpeta_equipo):
    return os.path.join(carpeta_equipo, "reportes")


# reportes/<PEM>/<AAAA-MM>/<Archivo>.csv  (una carpeta por PEM y dentro una por mes)
ARCHIVOS = {"solicitudes": "Solicitudes.csv", "pausas": "Pausas.csv", "conexion": "Conexion.csv",
            "horas_extra": "Horas extra.csv"}


def carpeta_pem(nombre):
    return re.sub(r"[^\w\- ]", "_", " ".join(str(nombre).split())).strip() or "sin_nombre"


def archivo(carpeta_equipo, tipo, nombre, cuando):
    return os.path.join(carpeta(carpeta_equipo), carpeta_pem(nombre), cuando.strftime("%Y-%m"), ARCHIVOS[tipo])


_VIEJO = re.compile(r"^(%s)_(\d{4}-\d{2})_(.+)\.csv$" % "|".join(ARCHIVOS))


def migrar(carpeta_equipo):
    """Los reportes de antes (reportes/<tipo>_<mes>_<PEM>.csv, todos juntos) pasan a la carpeta de su PEM.
    El nombre del PEM se toma de la columna PEM (asi se conservan las tildes). Devuelve cuantos movio."""
    base = carpeta(carpeta_equipo)
    try:
        nombres = [n for n in os.listdir(base) if _VIEJO.match(n)]
    except OSError:
        return 0
    movidos = 0
    for n in nombres:
        tipo, mes, pem = _VIEJO.match(n).groups()
        origen = os.path.join(base, n)
        try:
            with open(origen, encoding="utf-8-sig", newline="") as f:
                filas = list(csv.reader(io.StringIO(f.read()), delimiter=SEP))
            if len(filas) > 1 and filas[1] and filas[1][0].strip():
                pem = filas[1][0].strip()
            destino = os.path.join(base, carpeta_pem(pem), mes, ARCHIVOS[tipo])
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            if not os.path.exists(destino):
                os.replace(origen, destino)
            else:                                   # ya habia filas nuevas: se juntan (sin repetir el encabezado)
                with open(destino, "a", encoding="utf-8", newline="") as f:
                    csv.writer(f, delimiter=SEP).writerows(filas[1:])
                os.remove(origen)
            movidos += 1
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    return movidos


# ---------------------------------------------------------------------------------------------- escribir
def _escribir_fila(carpeta_equipo, tipo, nombre, cuando, fila):
    ruta = archivo(carpeta_equipo, tipo, nombre, cuando)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta) or os.path.getsize(ruta) == 0
    with open(ruta, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as f:
        w = csv.writer(f, delimiter=SEP)
        if nuevo:
            w.writerow(COLUMNAS[tipo])
        w.writerow(fila)


def _pendientes():
    from . import cola
    return cola._leer("reportes_pendientes.json", [])


def agregar(carpeta_equipo, tipo, nombre, cuando, fila):
    """Agrega una fila al reporte del PEM. Si no hay carpeta o falla, la guarda local para reintentar.
    Devuelve True si quedo escrita en la carpeta del equipo."""
    from . import cola
    fila = ["" if v is None else str(v) for v in fila]
    pend = _pendientes()
    pend.append({"tipo": tipo, "nombre": nombre, "cuando": cuando.isoformat(timespec="seconds"), "fila": fila})
    if not carpeta_equipo or not nombre:
        cola._escribir("reportes_pendientes.json", pend[-2000:])
        return False
    quedan = []
    for p in pend:
        try:
            _escribir_fila(carpeta_equipo, p["tipo"], p["nombre"], _dt(p["cuando"]) or cuando, p["fila"])
        except OSError:
            quedan.append(p)
    cola._escribir("reportes_pendientes.json", quedan[-2000:])
    return not quedan


# ---------------------------------------------------------------------------------------------- pausas
def registrar_pausa(carpeta_equipo, nombre, pausa, fin, como):
    ini = _dt((pausa or {}).get("desde"))
    hasta = _dt((pausa or {}).get("hasta"))
    if not ini:
        return False
    elegidos = int(round((hasta - ini).total_seconds() / 60.0)) if hasta else ""
    return agregar(carpeta_equipo, "pausas", nombre, ini, [
        nombre, fecha(ini), hora(ini), hora(fin), minutos(ini, fin), elegidos, pausa.get("razon", ""), como])


# ---------------------------------------------------------------------------------------------- conexion
GAP_S = 3 * 60        # sin publicar mas de esto = estuvo desconectado (app cerrada, PC dormido o sin red)


def _tramo(carpeta_equipo, nombre, estado, desde, hasta):
    """Escribe el tramo (partido a medianoche). No se registran los tramos desconectados ni los de 0 min."""
    if estado not in ESTADOS or hasta <= desde:
        return
    while desde.date() < hasta.date():
        medianoche = datetime.combine(desde.date() + timedelta(days=1), datetime.min.time())
        _tramo(carpeta_equipo, nombre, estado, desde, medianoche - timedelta(seconds=1))
        desde = medianoche
    if (hasta - desde).total_seconds() >= 30:
        agregar(carpeta_equipo, "conexion", nombre, desde,
                [nombre, fecha(desde), hora(desde), hora(hasta), ESTADOS[estado], minutos(desde, hasta)])


def seguir_conexion(carpeta_equipo, nombre, estado, ahora=None):
    """Cada publicacion de presencia (1 min): si cambio el estado (Activo / Ausente / En pausa) o hubo un hueco,
    escribe el tramo que termino. El estado en curso se guarda local (conexion.json)."""
    from . import cola
    ahora = ahora or datetime.now()
    with cola._bloqueo():
        e = cola._leer("conexion.json", {})
        desde, visto = _dt(e.get("desde")), _dt(e.get("visto"))
        if not desde or not visto or e.get("nombre") != nombre:
            e = {"nombre": nombre, "estado": estado, "desde": ahora.isoformat(timespec="seconds")}
        elif (ahora - visto).total_seconds() > GAP_S:                    # estuvo cerrada / sin red
            _tramo(carpeta_equipo, nombre, e.get("estado"), desde, visto)
            e = {"nombre": nombre, "estado": estado, "desde": ahora.isoformat(timespec="seconds")}
        elif e.get("estado") != estado:
            _tramo(carpeta_equipo, nombre, e.get("estado"), desde, ahora)
            e = {"nombre": nombre, "estado": estado, "desde": ahora.isoformat(timespec="seconds")}
        e["visto"] = ahora.isoformat(timespec="seconds")
        cola._escribir("conexion.json", e)


def cerrar_conexion(carpeta_equipo, nombre, ahora=None):
    """Al cerrar la app: escribe el tramo en curso."""
    from . import cola
    ahora = ahora or datetime.now()
    with cola._bloqueo():
        e = cola._leer("conexion.json", {})
        desde = _dt(e.get("desde"))
        if desde and e.get("nombre") == nombre:
            _tramo(carpeta_equipo, nombre, e.get("estado"), desde, ahora)
        cola._escribir("conexion.json", {})


# ---------------------------------------------------------------------------------------------- solicitudes
ORIGEN = {"auto": "Autoasignada", "admin": "Asignada por el admin", "central": "Servidor central",
          "sharepoint": "Asignada en SharePoint"}


def justificacion(j):
    from . import tiempos
    if not j:
        return ""
    if j.get("tipo") == "pem":
        return tiempos.DEMORA_PEM
    partes = [str(j.get("observacion") or "").strip()]
    if j.get("fotos"):
        partes.append("(%d foto(s))" % len(j["fotos"]))
    return " ".join(p for p in partes if p)


def registrar_solicitud(carpeta_equipo, nombre, rec, sol_cola=None, ahora=None):
    """Una fila por cierre (Forms o SharePoint). Si se cambia el resultado despues de cerrada, otra fila
    marcada 'Corrección'. Devuelve 'Cierre' / 'Corrección' o None si no habia nada nuevo."""
    from . import tiempos
    ahora = ahora or datetime.now()
    firma = "|".join(str(rec.get(k) or "") for k in ("resultado", "causa", "observacion"))
    if rec.get("reporte_firma") == firma:
        return None
    registro = "Corrección" if rec.get("reporte_firma") else "Cierre"
    m = tiempos.medir(rec, sol_cola, ahora)
    cierre = m["fin"] or ahora
    ini = m["inicio"]
    origen = ORIGEN.get((sol_cola or {}).get("origen") or "", (sol_cola or {}).get("origen") or "")
    agregar(carpeta_equipo, "solicitudes", nombre, cierre, [
        nombre, fecha(cierre), rec.get("id") or rec.get("key") or "", rec.get("rr", ""), m["red"], origen,
        hora(ini) if ini else "", hora(cierre), minutos(ini, cierre) if ini else "", m["limite"],
        "Sí" if m["excedido"] else "No", rec.get("resultado", ""), rec.get("causa", ""),
        " ".join(str(rec.get("observacion") or "").split()), justificacion(rec.get("demora")), registro])
    rec["reporte_firma"] = firma
    return registro


# ---------------------------------------------------------------------------------------------- plantillas por resultado
# reportes/<PEM>/<Exitosas|No exitosas|Escalamiento>/<AAAA-MM>/<solicitud>_<RR>.txt
CARPETA_RESULTADO = {"Exitosa": "Exitosas", "No exitosa": "No exitosas", "Escalamiento": "Escalamiento"}


def _nombre_archivo(rec):
    partes = [str(rec.get("id") or rec.get("key") or "").strip(), re.sub(r"\D", "", str(rec.get("rr") or ""))]
    base = "_".join(p for p in partes if p) or "solicitud"
    return re.sub(r"[^\w\-]", "_", base) + ".txt"


# Todas las solicitudes del equipo por mes y dia (carpeta que creo el equipo en reportes):
# reportes/SOLICITUDES/<11 Noviembre 2026>/<20>/<solicitud>_<RR> - <Resultado> - <PEM>.txt
SOLICITUDES = "SOLICITUDES"
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre")


def carpeta_dia(carpeta_equipo, cuando):
    """reportes/SOLICITUDES/11 Noviembre 2026/20 (el numero adelante: Windows las ordena bien)."""
    mes = "%02d %s %d" % (cuando.month, MESES[cuando.month - 1], cuando.year)
    return os.path.join(carpeta(carpeta_equipo), SOLICITUDES, mes, "%02d" % cuando.day)


def _guardar_en_dia(carpeta_equipo, nombre, rec, est, texto, cuando):
    base = os.path.splitext(_nombre_archivo(rec))[0]
    dia = carpeta_dia(carpeta_equipo, cuando)
    os.makedirs(dia, exist_ok=True)
    pem = carpeta_pem(nombre)
    for f in os.listdir(dia):                       # si cambio el resultado, queda solo el nuevo
        if f.startswith(base + " - ") and f.endswith(" - %s.txt" % pem):
            os.remove(os.path.join(dia, f))
    destino = os.path.join(dia, "%s - %s - %s.txt" % (base, est, pem))
    with open(destino, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(texto.replace("\r\n", "\n"))
    return destino


def ordenar_existentes(carpeta_equipo):
    """Pasa a SOLICITUDES/<mes>/<dia> las plantillas que ya estaban en las carpetas de resultado de cada PEM (usa
    la fecha del archivo). No repite las que ya estan. Devuelve cuantas copio."""
    import shutil
    base = carpeta(carpeta_equipo)
    n = 0
    try:
        pems = [p for p in os.listdir(base) if p != SOLICITUDES and os.path.isdir(os.path.join(base, p))]
    except OSError:
        return 0
    inverso = {v: k for k, v in CARPETA_RESULTADO.items()}
    for pem in pems:
        for sub, est in inverso.items():
            raiz = os.path.join(base, pem, sub)
            for actual, _dirs, archivos in os.walk(raiz):
                for f in archivos:
                    if not f.endswith(".txt"):
                        continue
                    origen = os.path.join(actual, f)
                    dia = carpeta_dia(carpeta_equipo, datetime.fromtimestamp(os.path.getmtime(origen)))
                    destino = os.path.join(dia, "%s - %s - %s.txt" % (os.path.splitext(f)[0], est, pem))
                    if os.path.exists(destino):
                        continue
                    os.makedirs(dia, exist_ok=True)
                    shutil.copy2(origen, destino)
                    n += 1
    return n


def guardar_plantilla(carpeta_equipo, nombre, rec, ahora=None):
    """Al cerrar la solicitud, su plantilla queda en la carpeta del PEM segun el resultado y en
    SOLICITUDES/<mes>/<dia> (todas las del equipo). Si despues se cambia el resultado, se mueve.
    Devuelve la ruta (la de la carpeta del PEM) o None."""
    from . import estados
    est = estados.normalizar((rec or {}).get("resultado") or "")
    sub = CARPETA_RESULTADO.get(est)
    texto = str((rec or {}).get("preview") or "")
    if not (carpeta_equipo and nombre and sub and texto.strip()):
        return None
    cuando = _dt(rec.get("documentada_en") or rec.get("cerrada_en") or "") or ahora or datetime.now()
    archivo_txt = _nombre_archivo(rec)
    base = os.path.join(carpeta(carpeta_equipo), carpeta_pem(nombre))
    mes = cuando.strftime("%Y-%m")
    for otra in CARPETA_RESULTADO.values():
        if otra != sub:
            vieja = os.path.join(base, otra, mes, archivo_txt)
            if os.path.isfile(vieja):
                os.remove(vieja)
    destino = os.path.join(base, sub, mes, archivo_txt)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(texto.replace("\r\n", "\n"))
    _guardar_en_dia(carpeta_equipo, nombre, rec, est, texto, cuando)
    return destino


# ---------------------------------------------------------------------------------------------- leer / resumen
def leer(carpeta_equipo, tipo, mes):
    """Filas (dict) de todos los PEM de un tipo y mes (datetime/date)."""
    out = []
    base = carpeta(carpeta_equipo)
    migrar(carpeta_equipo)
    try:
        pems = sorted(n for n in os.listdir(base) if n != SOLICITUDES and os.path.isdir(os.path.join(base, n)))
    except OSError:
        return out
    for pem in pems:
        ruta = os.path.join(base, pem, mes.strftime("%Y-%m"), ARCHIVOS[tipo])
        if not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, encoding="utf-8-sig", newline="") as f:
                out.extend(csv.DictReader(io.StringIO(f.read()), delimiter=SEP))
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    return out


def resumen_dia(carpeta_equipo, dia):
    """{PEM: {...}} del dia: solicitudes, resultados, minutos promedio, superadas, minutos por estado, pausas."""
    f = fecha(dia)
    res = {}

    def fila(n):
        return res.setdefault(n, {"cerradas": 0, "exitosas": 0, "no_exitosas": 0, "escalamientos": 0,
                                  "min_total": 0.0, "con_tiempo": 0, "superaron": 0, "activo": 0.0,
                                  "ausente": 0.0, "pausa": 0.0, "pausas": 0, "extra": 0.0})

    for r in leer(carpeta_equipo, "solicitudes", dia):
        if r.get("Fecha") != f:
            continue
        x = fila(r.get("PEM", ""))
        if r.get("Registro") == "Corrección":
            x["corr"] = x.get("corr", 0) + 1
        else:
            x["cerradas"] += 1
            if r.get("Minutos"):
                x["min_total"] += _num(r["Minutos"])
                x["con_tiempo"] += 1
            if r.get("Superó el tiempo") == "Sí":
                x["superaron"] += 1
        est = (r.get("Resultado") or "").lower()
        clave = {"exitosa": "exitosas", "no exitosa": "no_exitosas", "escalamiento": "escalamientos"}.get(est)
        if clave and r.get("Registro") != "Corrección":
            x[clave] += 1
    for r in leer(carpeta_equipo, "conexion", dia):
        if r.get("Fecha") == f:
            clave = {"Activo": "activo", "Ausente": "ausente", "En pausa": "pausa"}.get(r.get("Estado"))
            if clave:
                fila(r.get("PEM", ""))[clave] += _num(r.get("Minutos"))
    for r in leer(carpeta_equipo, "pausas", dia):
        if r.get("Fecha") == f:
            fila(r.get("PEM", ""))["pausas"] += 1
    for r in leer(carpeta_equipo, "horas_extra", dia):
        if r.get("Fecha") == f:
            fila(r.get("PEM", ""))["extra"] += _num(r.get("Minutos"))
    for x in res.values():
        x["promedio"] = (x["min_total"] / x["con_tiempo"]) if x["con_tiempo"] else 0.0
    return res


def extra_mes(carpeta_equipo, mes):
    """{PEM: minutos de horas extra en el mes}."""
    out = {}
    for r in leer(carpeta_equipo, "horas_extra", mes):
        out[r.get("PEM", "")] = out.get(r.get("PEM", ""), 0.0) + _num(r.get("Minutos"))
    return out


def h_min(minutos):
    """95 -> '1 h 35 min'; 0 -> '—'."""
    m = int(round(minutos or 0))
    if not m:
        return "—"
    return ("%d h %02d min" % divmod(m, 60)) if m >= 60 else "%d min" % m
