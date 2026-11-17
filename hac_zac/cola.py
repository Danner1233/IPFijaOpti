"""Cola de solicitudes + reparto entre ingenieros.

* ingenieros.json  -> [{"nombre", "activo", "whatsapp"}]  (se activan/desactivan a mano)
* cola.json        -> solicitudes recibidas de la lista de SharePoint, con su estado y su ingeniero.

Estados de la cola: nueva -> asignada -> en_proceso -> por_documentar -> terminada (solo al documentar).
El reparto es por menor carga (casos abiertos); empata el que lleva mas tiempo sin recibir.
Se atiende en orden de llegada (FIFO): los 30 minutos corren desde la fecha de solicitud.
"""
import functools
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime

from . import log as _log
from .rutas import data_dir

LOG = _log.obtener("cola")

ABIERTOS = ("asignada", "en_proceso", "por_documentar")

# nombre interno de la columna de SharePoint -> clave nuestra
CAMPOS_SP = {
    "ID": "id", "Created": "creada", "PEM_ASIGNADO": "pem", "Est_Seg": "est_seg",
    "PROPIEDAD_RED": "propiedad_red", "field_1": "rr", "field_2": "cliente", "field_3": "ot",
    "field_12": "serial", "field_13": "mac", "Regional": "regional", "field_4": "ciudad",
    "ALIADO_CAMPO": "aliado", "field_17": "tipo_actividad", "field_8": "codigo", "field_14": "megas",
    "Requiere_x0020_Configurar_x0020_": "bridge", "REQUIERE_CONFIGURACI_x00d3_N_DMZ": "dmz",
    "SERVICIO_SOBRE_RED_ATP_x003f_": "sobre_atp", "field_15": "tecnico", "field_16": "celular_tecnico",
}


def _ruta(nombre):
    return data_dir() / nombre


def _leer(nombre, defecto):
    try:
        return json.loads(_ruta(nombre).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto
    except (OSError, ValueError):
        LOG.exception("No se pudo leer %s (se usa el valor por defecto)", nombre)
        return defecto


# ---- bloqueo entre procesos: SharePoint, correo, administrador y la interfaz escriben cola.json a la vez.
# Sin esto, dos "leer -> modificar -> guardar" simultáneos se pisan y se pierde un cambio.
_LOCAL = threading.RLock()
_PROFUNDIDAD = [0]


def _tomar_archivo(espera=5.0, rancio=15.0):
    ruta = _ruta(".cola.lock")
    limite = time.time() + espera
    while True:
        try:
            fd = os.open(str(ruta), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - ruta.stat().st_mtime > rancio:      # lo dejó un proceso caído
                    ruta.unlink()
                    continue
            except OSError:
                pass
            if time.time() > limite:
                LOG.warning("No se obtuvo el bloqueo de la cola en %.0f s; se continúa sin él", espera)
                return False
            time.sleep(0.05)


@contextmanager
def _bloqueo():
    with _LOCAL:
        propio = False
        if _PROFUNDIDAD[0] == 0:
            propio = _tomar_archivo()
        _PROFUNDIDAD[0] += 1
        try:
            yield
        finally:
            _PROFUNDIDAD[0] -= 1
            if _PROFUNDIDAD[0] == 0 and propio:
                try:
                    _ruta(".cola.lock").unlink()
                except OSError:
                    pass


def bloqueado(fn):
    """Decorador para toda función que modifica cola.json o ingenieros.json."""
    @functools.wraps(fn)
    def envoltura(*a, **k):
        with _bloqueo():
            return fn(*a, **k)
    return envoltura


def _escribir(nombre, datos):
    r = _ruta(nombre)
    tmp = r.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(r))


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------------------ ingenieros
def ingenieros():
    return _leer("ingenieros.json", [])


@bloqueado
def guardar_ingenieros(lista):
    _escribir("ingenieros.json", lista)


@bloqueado
def agregar_ingeniero(nombre, whatsapp=""):
    lista = ingenieros()
    if not any(i["nombre"].lower() == nombre.lower() for i in lista):
        lista.append({"nombre": nombre.strip(), "activo": False, "whatsapp": whatsapp, "ultimo": ""})
        guardar_ingenieros(lista)


@bloqueado
def quitar_ingeniero(nombre):
    guardar_ingenieros([i for i in ingenieros() if i["nombre"] != nombre])


@bloqueado
def poner_activo(nombre, activo):
    lista = ingenieros()
    for i in lista:
        if i["nombre"] == nombre:
            i["activo"] = bool(activo)
    guardar_ingenieros(lista)


# ------------------------------------------------------------------------------ cola
def _cola():
    return _leer("cola.json", {"solicitudes": []})


def solicitudes():
    return _cola()["solicitudes"]


def _texto_plantilla(d):
    """Mismo formato que el correo, para que el lector de plantilla de la aplicacion lo entienda."""
    def n(x):
        return str(x or "").strip()
    return "\n".join([
        "++++++SOLICITUD ID: %s++++++" % n(d.get("id")),
        "PROPIEDAD RED: %s" % n(d.get("propiedad_red")),
        "CUENTA RR: %s" % n(d.get("rr")),
        "OT/LLs RR: %s" % n(d.get("ot")),
        "NOMBRE CLIENTE: %s" % n(d.get("cliente")),
        "REGIONAL: %s" % n(d.get("regional")),
        "CIUDAD: %s" % n(d.get("ciudad")),
        "CÓDIGO SERVICIO: %s" % n(d.get("codigo")),
        "SERIAL ONT: %s" % n(d.get("serial")),
        "MAC ONT: %s" % n(d.get("mac")),
        "ANCHO DE BANDA: %s" % n(d.get("megas")),
        "NOMBRE TÉCNICO: %s" % n(d.get("tecnico")),
        "CELULAR TÉCNICO: %s" % n(d.get("celular_tecnico")),
        "ALIADO: %s" % n(d.get("aliado")),
        "TIPO ACTIVIDAD: %s" % n(d.get("tipo_actividad")),
        "REQUIERE IP BRIDGE? %s" % n(d.get("bridge")),
        "REQUIERE DMZ? %s" % n(d.get("dmz")),
    ]) + "\n"


def desde_sp(item):
    """Item de la lista de SharePoint (REST) -> solicitud nuestra."""
    d = {}
    for k, v in CAMPOS_SP.items():
        val = item.get(k)
        if isinstance(val, dict):                # personas / busquedas: {"Title": ...}
            val = val.get("Title") or val.get("Name") or ""
        d[v] = "" if val is None else val
    d["rr"] = solo_digitos(d.get("rr"))           # cuenta RR siempre sin puntos
    d["ot"] = solo_digitos(d.get("ot")) or str(d.get("ot") or "")
    d["id"] = str(d["id"])
    d["txt_sol"] = _texto_plantilla(d)
    return d


def _plano(t):
    import unicodedata
    return " ".join(unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower().split())


ESTADOS_FINALES = ("exitosa", "no exitosa", "escalamiento", "cancelada")


def nombre_configurado():
    """Mi nombre tal como esta registrado en la columna PEM_ASIGNADO (ajustes.json, clave pem_nombre)."""
    return str(_leer("ajustes.json", {}).get("pem_nombre", "") or "").strip()


def auto_asignar_configurado():
    return bool(_leer("ajustes.json", {}).get("auto_asignar", True))


# ---- estado final hacia SharePoint ------------------------------------------------------------
# Al DOCUMENTAR una solicitud se pide escribir su Est_Seg (Exitosa / No exitosa / Escalamiento) en la lista.
# Quien tiene la sesion de SharePoint (sp_lector) lo escribe y recien entonces puede tomar otra solicitud.
ESTADOS_ASIGNABLES = ("exitosa", "no exitosa", "escalamiento")
SP_PENDIENTES = "sp_pendientes.json"
MAX_INTENTOS_SP = 3


@bloqueado
def pedir_estado_sp(id_, estado):
    """Anota que la solicitud `id_` ya esta documentada y que SharePoint debe quedar en `estado`."""
    datos = _leer(SP_PENDIENTES, {})
    datos[str(id_)] = {"est_seg": estado, "ok": False, "intentos": 0, "pedido": _ahora(), "error": ""}
    _escribir(SP_PENDIENTES, datos)


def estados_sp():
    return _leer(SP_PENDIENTES, {})


REGISTRO_SP = "registro_sharepoint.jsonl"


def registrar_escritura_sp(id_, campo, antes, despues, ok, motivo="", **extra):
    """Auditoria: una linea por cada escritura en SharePoint (fecha, solicitud, campo, valor anterior y nuevo,
    resultado). Sirve para revisar o deshacer a mano. Nunca falla: si no puede escribir, solo lo anota en el log."""
    fila = {"fecha": datetime.now().isoformat(timespec="seconds"), "id": str(id_), "campo": campo,
            "antes": antes or "", "despues": despues or "", "ok": bool(ok), "motivo": (motivo or "")[:200]}
    fila.update(extra)
    try:
        with open(str(data_dir() / REGISTRO_SP), "a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    except Exception:
        _log.obtener("cola").exception("no pude anotar la escritura en SharePoint")


def leer_registro_sp(ultimas=200):
    try:
        with open(str(data_dir() / REGISTRO_SP), encoding="utf-8") as f:
            lineas = f.readlines()[-ultimas:]
    except Exception:
        return []
    out = []
    for ln in lineas:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def pendientes_sp():
    """{id: estado} de lo que falta escribir en SharePoint."""
    return {i: v["est_seg"] for i, v in estados_sp().items() if not v.get("ok") and v.get("intentos", 0) < MAX_INTENTOS_SP}


@bloqueado
def resultado_sp(id_, ok, error=""):
    datos = _leer(SP_PENDIENTES, {})
    v = datos.get(str(id_))
    if not v:
        return
    v["ok"] = bool(ok)
    v["error"] = "" if ok else str(error)[:200]
    if not ok:
        v["intentos"] = v.get("intentos", 0) + 1
    _escribir(SP_PENDIENTES, datos)


def abiertas_sp(items, nombre, max_horas=24):
    """Mis solicitudes en SharePoint que NO se pueden dejar atras: asignadas a mi y con Est_Seg distinto de
    Exitosa / No exitosa / Escalamiento. Una ya documentada (aunque SharePoint no la haya aceptado) no cuenta.
    Devuelve la lista de ids."""
    from datetime import datetime
    documentadas = set(estados_sp())
    abiertas = []
    for it in items:
        d = desde_sp(it)
        if not (d.get("pem") and es_mia({**d, "est_seg": ""}, nombre)):
            continue
        if d["id"] in documentadas:
            continue
        if _plano(d.get("est_seg")) in ESTADOS_ASIGNABLES:
            continue
        creada = _a_local(d.get("creada"))
        if creada and (datetime.now() - creada).total_seconds() > max_horas * 3600:
            continue
        abiertas.append(d["id"])
    return abiertas


def estoy_libre(nombre):
    """No tengo ninguna solicitud abierta en la cola."""
    return not mis_casos(nombre)


def es_libre(it):
    """Libre = la columna PEM_ASIGNADO esta VACIA (y no es una solicitud ya cerrada ni de apoyo)."""
    d = desde_sp(it)
    if str(d.get("pem") or "").strip():
        return False
    if _plano(d.get("est_seg")) in ESTADOS_FINALES:
        return False
    return _plano(it.get("ActivApoyo")) in ("", "no")


def elegir_libre(items):
    """La solicitud libre mas antigua (PEM_ASIGNADO vacio). Devuelve el item crudo o None."""
    libres = [it for it in items if es_libre(it)]
    return min(libres, key=lambda i: str(i.get("Created") or ""), default=None)


def es_mia(d, nombre):
    """Solicitud asignada a mi nombre en SharePoint y todavia no cerrada. Sin acentos ni mayusculas;
    basta con que todas las palabras de mi nombre aparezcan en la columna."""
    pem, mio = _plano(d.get("pem")), _plano(nombre)
    if not mio or not pem:
        return False
    if _plano(d.get("est_seg")) in ESTADOS_FINALES:
        return False
    return all(w in pem for w in mio.split())


@bloqueado
def registrar_mia(d, nombre):
    """Agrega la solicitud a la cola ya asignada a mi. True si es nueva."""
    c = _cola()
    if any(s["id"] == d["id"] for s in c["solicitudes"]):
        return False
    c["solicitudes"].append({"id": d["id"], "estado": "asignada", "asignado": nombre, "recibida": _ahora(),
                             "asignada_en": _ahora(), "plantilla": False, "datos": d})
    _escribir("cola.json", c)
    return True


@bloqueado
def registrar_desde_central(d, nombre):
    """Caso que me asigno el servidor central. Queda en mi cola como 'asignada' y marcado origen=central
    (su Est_Seg lo escribe el central, no mi lector de SharePoint). True si es nuevo."""
    c = _cola()
    for s in c["solicitudes"]:
        if s["id"] == str(d["id"]):
            if s.get("origen") != "central":
                s["origen"] = "central"
                _escribir("cola.json", c)
            return False
    datos = dict(d)
    datos.setdefault("txt_sol", _texto_plantilla(datos))
    c["solicitudes"].append({"id": str(d["id"]), "estado": "asignada", "asignado": nombre, "recibida": _ahora(),
                             "asignada_en": _ahora(), "plantilla": False, "datos": datos, "origen": "central"})
    _escribir("cola.json", c)
    return True


def es_del_central(id_):
    return any(s["id"] == str(id_) and s.get("origen") == "central" for s in solicitudes())


def rr_sin_correo():
    """Cuentas RR de mis solicitudes abiertas que todavia no tienen la plantilla del correo."""
    return {solo_digitos(s["datos"].get("rr")) for s in solicitudes()
            if s["estado"] in ABIERTOS and not s.get("plantilla") and solo_digitos(s["datos"].get("rr"))}


def es_nueva(d, estados_nuevos=("", "pendiente", "nueva")):
    """Por defecto: sin ingeniero y sin estado de seguimiento (ajustable cuando veamos la lista real)."""
    return not str(d.get("pem") or "").strip() and str(d.get("est_seg") or "").strip().lower() in estados_nuevos


@bloqueado
def registrar_entrada(d):
    """Agrega la solicitud a la cola si no estaba. Devuelve True si es nueva."""
    c = _cola()
    if any(s["id"] == d["id"] for s in c["solicitudes"]):
        return False
    c["solicitudes"].append({"id": d["id"], "estado": "nueva", "asignado": "", "recibida": _ahora(),
                             "asignada_en": "", "datos": d})
    _escribir("cola.json", c)
    return True


@bloqueado
def asignar_pendientes(solo_libres=True):
    """Asigna las 'nueva' a ingenieros ACTIVOS que no tengan ninguna solicitud abierta (solo_libres).
    Si no hay ninguno libre, la solicitud espera en la cola. Devuelve [(id, ingeniero)]."""
    c = _cola()
    activos = [i for i in ingenieros() if i.get("activo")]
    hechas = []
    if not activos:
        return hechas
    ing_all = ingenieros()
    for s in sorted((x for x in c["solicitudes"] if x["estado"] == "nueva"),
                    key=lambda x: str(x["datos"].get("creada") or x["recibida"])):
        carga = {i["nombre"]: sum(1 for x in c["solicitudes"] if x["asignado"] == i["nombre"] and x["estado"] in ABIERTOS)
                 for i in activos}
        candidatos = [i for i in activos if carga[i["nombre"]] == 0] if solo_libres else activos
        if not candidatos:
            break
        elegido = min(candidatos, key=lambda i: (carga[i["nombre"]], i.get("ultimo") or ""))
        s["estado"], s["asignado"], s["asignada_en"] = "asignada", elegido["nombre"], _ahora()
        for i in ing_all:
            if i["nombre"] == elegido["nombre"]:
                i["ultimo"] = s["asignada_en"]
        elegido["ultimo"] = s["asignada_en"]
        hechas.append((s["id"], elegido["nombre"]))
    if hechas:
        _escribir("cola.json", c)
        guardar_ingenieros(ing_all)
    return hechas


def mis_casos(nombre):
    """Casos abiertos de un ingeniero, en orden de llegada (el primero es el turno 1)."""
    return [s for s in solicitudes() if s["asignado"] == nombre and s["estado"] in ABIERTOS]


def turno(id_):
    s = next((x for x in solicitudes() if x["id"] == str(id_)), None)
    if not s or not s["asignado"]:
        return 0
    cola = mis_casos(s["asignado"])
    return 1 + [x["id"] for x in cola].index(s["id"]) if s["id"] in [x["id"] for x in cola] else 0


@bloqueado
def cambiar_estado(id_, estado):
    c = _cola()
    for s in c["solicitudes"]:
        if s["id"] == str(id_):
            s["estado"] = estado
    _escribir("cola.json", c)


# ------------------------------------------------------------------------------ correo (plantilla completa)
def solo_digitos(x):
    """64.270.704 -> 64270704 ; 22916869.0000000 -> 22916869"""
    t = str(x or "").strip()
    import re
    m = re.fullmatch(r"(\d+)\.0+", t)
    if m:
        t = m.group(1)                           # 22916869.0000000 / 64270704.0
    return "".join(ch for ch in t if ch.isdigit())


def _a_local(iso):
    """ISO (con 'Z' de SharePoint o sin zona) -> datetime local sin zona."""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


TOLERANCIA_S = 300      # un correo puede estar fechado hasta 5 min antes que la lista (relojes distintos)


def correo_es_actual(sol, recibido):
    """True si el correo (hora conocida) no es anterior a la solicitud de la lista: descarta cuentas viejas."""
    sp, co = _a_local(sol["datos"].get("creada") or sol.get("recibida")), _a_local(recibido)
    if not sp or not co:
        return None                      # no se sabe
    return (co - sp).total_seconds() >= -TOLERANCIA_S


def pendientes_correo():
    """{cuenta RR: solicitud} de mis solicitudes abiertas que aun no tienen la plantilla."""
    return {solo_digitos(s["datos"].get("rr")): s for s in solicitudes()
            if s["estado"] in ABIERTOS and not s.get("plantilla") and solo_digitos(s["datos"].get("rr"))}


@bloqueado
def registrar_correo(texto, recibido=None, crear=False):
    """Une el correo con la solicitud de la lista (misma SOLICITUD ID) y guarda la plantilla completa.
    Si el correo llega antes que la lista, crea la solicitud. Devuelve (id, creada) o None si no trae ID."""
    from . import plantilla
    p = plantilla.parsear_solicitud(texto)
    id_ = p.get("solicitud_id")
    if not id_:
        return None
    recibido_dado = bool(recibido)
    recibido = recibido or _ahora()
    nuevo = {
        "id": id_, "propiedad_red": p["propiedad_red"], "rr": p["rr"], "ot": p["ot"], "cliente": p["cliente"],
        "serial": p["serial_ont"], "mac": p["mac_ont"], "megas": p["ancho_banda"],
        "bridge": "SI" if p["bridge"] else "NO", "txt_sol": plantilla.extraer_solicitud(texto),
    }
    nuevo["rr"] = solo_digitos(nuevo["rr"])
    c = _cola()
    for s in c["solicitudes"]:
        # misma SOLICITUD ID, o (si cambia el ID) misma cuenta RR todavia sin plantilla
        mismo_id = s["id"] == id_
        # misma cuenta RR solo vale si el correo es de AHORA (hay cuentas viejas con el mismo RR)
        misma_rr = (not s.get("plantilla") and nuevo["rr"] and solo_digitos(s["datos"].get("rr")) == nuevo["rr"]
                    and recibido_dado and correo_es_actual(s, recibido) is True)
        if mismo_id or misma_rr:
            s["datos"].update({k: v for k, v in nuevo.items() if v not in ("", None) and k != "id"})
            s["plantilla"] = True
            s["correo_en"] = recibido
            sp, co = _a_local(s["datos"].get("creada") or s["recibida"]), _a_local(recibido)
            if sp and co:                         # cuanto tardo el correo despues de la lista
                s["demora_correo_s"] = int((co - sp).total_seconds())
            _escribir("cola.json", c)
            return s["id"], False
    if not crear:
        return None                               # correo de una solicitud que no es mia: se ignora
    c["solicitudes"].append({"id": id_, "estado": "nueva", "asignado": "", "recibida": _ahora(), "correo_en": recibido,
                             "asignada_en": "", "plantilla": True, "datos": nuevo})
    _escribir("cola.json", c)
    return id_, True


def siguiente_para_script(nombre):
    """Primer caso del ingeniero que ya tiene la plantilla completa y no ha empezado."""
    for s in mis_casos(nombre):
        if s["estado"] == "asignada" and s.get("plantilla"):
            return s
    return None
