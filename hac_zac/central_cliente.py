# -*- coding: utf-8 -*-
"""Conexion de la aplicacion del PEM con el servidor central de reparto.

Cada CADA_S segundos (latido): avisa que la aplicacion esta abierta y si el PEM esta Disponible, recibe sus casos
asignados (quedan en su Cola) y reporta los que ya documento para que el central escriba el Est_Seg en SharePoint.
Sin dependencias (urllib).
"""
import json
import threading
import urllib.error
import urllib.request

from . import cola, credenciales

CADA_S = 15
TIMEOUT_S = 8


def config(ajustes):
    """(url, token) o (None, None) si no esta configurado."""
    url = str((ajustes or {}).get("servidor_central") or "").strip().rstrip("/")
    token = credenciales.cargar().get("central_clave", "")
    if not url or not token:
        return None, None
    if "://" not in url:
        url = "http://" + url
    return url, token


def configurado(ajustes):
    return config(ajustes)[0] is not None


def enviar_latido(url, token, disponible, documentadas, timeout=TIMEOUT_S):
    """POST /latido. Devuelve el dict de respuesta; lanza ConnectionError con un mensaje claro si falla."""
    cuerpo = json.dumps({"disponible": bool(disponible), "documentadas": documentadas or {}}).encode("utf-8")
    req = urllib.request.Request(url + "/latido", data=cuerpo, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error") or str(e)
        except Exception:
            msg = str(e)
        raise ConnectionError(msg)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ConnectionError("Sin conexion con el servidor central (%s)" % getattr(e, "reason", e))


def documentadas_para_central():
    """{id: estado} de mis casos que vinieron del central, ya documentados y aun sin confirmar en SharePoint."""
    del_central = {s["id"] for s in cola.solicitudes() if s.get("origen") == "central"}
    return {i: v["est_seg"] for i, v in cola.estados_sp().items() if i in del_central and not v.get("ok")}


def aplicar_respuesta(resp):
    """Mete en mi cola los casos nuevos y marca como escritos en SharePoint los confirmados.
    Devuelve los ids nuevos."""
    nombre = resp.get("pem") or ""
    nuevos = []
    for d in resp.get("casos") or []:
        if d.get("id") and cola.registrar_desde_central(d, nombre):
            nuevos.append(str(d["id"]))
    for i in resp.get("confirmadas") or []:
        cola.resultado_sp(str(i), True, "")
    return nuevos


class Conexion:
    """Hilo de latidos. `aviso(estado)` se llama desde el hilo con
    {"ok", "pem", "mensaje", "nuevos", "simulacion"}: la interfaz debe pasarlo a su hilo con after()."""

    def __init__(self, ajustes, aviso, cada=CADA_S):
        self.ajustes, self.aviso, self.cada = ajustes, aviso, cada
        self.disponible = False
        self._parar = threading.Event()
        self._ya = threading.Event()
        self._hilo = None

    def iniciar(self):
        if self._hilo and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._ciclo, daemon=True, name="latido-central")
        self._hilo.start()

    def detener(self):
        self._parar.set()
        self._ya.set()

    def cambiar_disponible(self, valor):
        self.disponible = bool(valor)
        self._ya.set()                                   # latir ya, sin esperar los 15 s

    def latir_una_vez(self):
        url, token = config(self.ajustes)
        if not url:
            return {"ok": False, "mensaje": "Reparto central sin configurar (Ajustes)."}
        try:
            resp = enviar_latido(url, token, self.disponible, documentadas_para_central())
        except ConnectionError as e:
            return {"ok": False, "mensaje": str(e)}
        nuevos = aplicar_respuesta(resp)
        return {"ok": True, "pem": resp.get("pem", ""), "nuevos": nuevos, "simulacion": bool(resp.get("simulacion")),
                "mensaje": "Conectado como %s" % resp.get("pem", "")}

    def _ciclo(self):
        while not self._parar.is_set():
            try:
                est = self.latir_una_vez()
            except Exception as e:                       # nunca matar el hilo
                est = {"ok": False, "mensaje": "Error: %s" % e}
            try:
                self.aviso(est)
            except Exception:
                pass
            self._ya.wait(self.cada)
            self._ya.clear()
