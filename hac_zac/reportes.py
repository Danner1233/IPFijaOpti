# -*- coding: utf-8 -*-
"""Registro y reporte del equipo en la carpeta compartida (OneDrive), para abrir en Excel.

<carpeta_equipo>/reportes/<tipo>_<AAAA-MM>_<Nombre>.csv   (tipo: pausas, conexion, solicitudes)

* Un archivo POR PEM y por mes: cada PC solo escribe el suyo, asi OneDrive no crea copias en conflicto.
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


def archivo(carpeta_equipo, tipo, nombre, cuando):
    seguro = re.sub(r"[^A-Za-z0-9_\- ]", "_", " ".join(str(nombre).split())).strip() or "sin_nombre"
    return os.path.join(carpeta(carpeta_equipo), "%s_%s_%s.csv" % (tipo, cuando.strftime("%Y-%m"), seguro))


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


# ---------------------------------------------------------------------------------------------- leer / resumen
def leer(carpeta_equipo, tipo, mes):
    """Filas (dict) de todos los PEM de un tipo y mes (datetime/date)."""
    out = []
    base = carpeta(carpeta_equipo)
    pref = "%s_%s_" % (tipo, mes.strftime("%Y-%m"))
    try:
        nombres = sorted(n for n in os.listdir(base) if n.startswith(pref) and n.endswith(".csv"))
    except OSError:
        return out
    for n in nombres:
        try:
            with open(os.path.join(base, n), encoding="utf-8-sig", newline="") as f:
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
