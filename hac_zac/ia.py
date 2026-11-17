# -*- coding: utf-8 -*-
"""IA (Azure OpenAI / Foundry, p. ej. gpt-5-mini) para ENTENDER lo que escribe el tecnico. Solo clasifica.

Configuracion en ia.json (carpeta del central):
    endpoint   : https://<su-recurso>.openai.azure.com   (o .services.ai.azure.com)
    deployment : nombre del despliegue (ej. gpt-5-mini)
    api_key    : (opcional, cifrada) si no se pone, se usa su sesion de Azure CLI ("az login", Entra ID)
Sin dependencias: REST con urllib; el token de Entra ID se pide a Azure CLI.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hac_zac_dpapi as dpapi  # noqa: E402

from .agente import INTENCIONES  # noqa: E402

RECURSO = "https://cognitiveservices.azure.com"
INSTRUCCIONES = (
    "Clasificas mensajes de WhatsApp de técnicos de campo que instalan servicios de internet con IP fija. "
    "Responde SOLO un JSON {\"intencion\": \"...\"} con una de estas intenciones:\n"
    "- saludo: solo saluda.\n"
    "- estado: pregunta cómo va, si ya quedó, cuánto falta.\n"
    "- direccionamiento: pide la IP, gateway, máscara, segmento o direccionamiento.\n"
    "- confirmar_si: (solo si se le preguntó si quedó todo en orden) dice que sí, que funciona.\n"
    "- confirmar_no: (solo si se le preguntó si quedó todo en orden) dice que no o reporta una falla.\n"
    "- otro: cualquier otra cosa (problemas, dudas técnicas, solicitudes al ingeniero).\n"
    "No respondas al técnico ni agregues texto: solo el JSON."
)


def cargar_config(carpeta):
    try:
        with open(os.path.join(carpeta, "ia.json"), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if c.get("api_key") and dpapi.es_cifrado(c["api_key"]):
        c["api_key"] = dpapi.descifrar(c["api_key"])
    return c if c.get("endpoint") and c.get("deployment") else None


def guardar_config(carpeta, c):
    datos = dict(c)
    if datos.get("api_key") and dpapi.disponible():
        datos["api_key"] = dpapi.cifrar(datos["api_key"])
    with open(os.path.join(carpeta, "ia.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def comando_az():
    """Como lanzar Azure CLI en este PC: az.cmd, o (instalador MSI nuevo) su propio python con -m azure.cli."""
    for c in (shutil.which("az.cmd"), r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
              r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"):
        if c and os.path.exists(c):
            return [c]
    for base in (r"C:\Program Files\Microsoft SDKs\Azure\CLI2", r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2"):
        py = os.path.join(base, "python.exe")
        if os.path.exists(py):
            return [py, "-IBm", "azure.cli"]
    c = shutil.which("az")
    if c and os.name != "nt":
        return [c]
    raise RuntimeError("No encuentro Azure CLI (az). Instálelo y ejecute: az login")


def url_chat(endpoint):
    e = endpoint.rstrip("/")
    if "/openai/" in e:
        return e if e.endswith("/chat/completions") else e + "/chat/completions"
    return e + "/openai/v1/chat/completions"


def interpretar(respuesta):
    """Texto del modelo -> intencion valida, o ValueError."""
    t = (respuesta or "").strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1]
    try:
        i = json.loads(t).get("intencion")
    except (ValueError, AttributeError):
        i = t.strip().strip('"').lower()
    if i not in INTENCIONES:
        raise ValueError("respuesta fuera de la lista: %r" % respuesta[:80])
    return i


class Clasificador:
    def __init__(self, config, timeout=12):
        self.c, self.timeout = config, timeout
        self._token, self._vence = None, 0

    def _autorizacion(self):
        if self.c.get("api_key"):
            return {"api-key": self.c["api_key"]}
        if not self._token or time.time() > self._vence - 300:
            flags = 0x08000000 if os.name == "nt" else 0
            r = subprocess.run(comando_az() + ["account", "get-access-token", "--resource", RECURSO, "-o", "json"],
                               capture_output=True, text=True, timeout=60, creationflags=flags)
            if r.returncode != 0:
                raise RuntimeError("Azure CLI no dio token (ejecute: az login): " + (r.stderr or "")[:200])
            d = json.loads(r.stdout)
            self._token = d["accessToken"]
            self._vence = float(d.get("expires_on") or time.time() + 1800)
        return {"Authorization": "Bearer " + self._token}

    def __call__(self, texto, esperando_confirmacion=False):
        contexto = ("Se le acaba de preguntar al técnico si quedó todo en orden." if esperando_confirmacion
                    else "No hay ninguna pregunta pendiente al técnico.")
        cuerpo = {"model": self.c["deployment"], "max_completion_tokens": 600,
                  "messages": [{"role": "system", "content": INSTRUCCIONES},
                               {"role": "user", "content": contexto + "\nMensaje del técnico: " + str(texto)[:1000]}]}
        if self.c.get("reasoning_effort", "low"):
            cuerpo["reasoning_effort"] = self.c.get("reasoning_effort", "low")
        h = {"Content-Type": "application/json"}
        h.update(self._autorizacion())
        req = urllib.request.Request(url_chat(self.c["endpoint"]), data=json.dumps(cuerpo).encode("utf-8"),
                                     headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError("Azure OpenAI respondio %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
        return interpretar(d["choices"][0]["message"].get("content") or "")
