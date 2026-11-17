# -*- coding: utf-8 -*-
"""WhatsApp Business Cloud API (Meta) sin dependencias.

Configuracion en whatsapp.json (carpeta del central). Los secretos (token y app_secret) van cifrados con DPAPI.
    phone_number_id  : el ID del numero (Meta for Developers > WhatsApp > Configuracion de la API)
    token            : token de acceso (el temporal dura 24 h; para uso real, token de usuario del sistema)
    verify_token     : palabra que usted inventa y pone igual en Meta al registrar el webhook
    app_secret       : "Clave secreta de la app" (Configuracion > Basica): valida que los mensajes vienen de Meta
    plantilla_inicio : (opcional) plantilla aprobada para escribirle primero al tecnico. Sin ella, WhatsApp solo
                       deja escribirle si el tecnico escribio en las ultimas 24 h.
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hac_zac_dpapi as dpapi  # noqa: E402

API = "https://graph.facebook.com/v21.0"
SECRETOS = ("token", "app_secret")


def cargar_config(carpeta):
    try:
        with open(os.path.join(carpeta, "whatsapp.json"), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    for k in SECRETOS:
        if c.get(k) and dpapi.es_cifrado(c[k]):
            c[k] = dpapi.descifrar(c[k])
    return c if c.get("phone_number_id") and c.get("token") else None


def guardar_config(carpeta, c):
    datos = dict(c)
    for k in SECRETOS:
        if datos.get(k) and dpapi.disponible():
            datos[k] = dpapi.cifrar(datos[k])
    with open(os.path.join(carpeta, "whatsapp.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------------------------- webhook
def verificar_suscripcion(params, verify_token):
    """GET del webhook: Meta manda hub.mode, hub.verify_token y hub.challenge. Devuelve el challenge o None."""
    if params.get("hub.mode") == "subscribe" and verify_token and \
            hmac.compare_digest(str(params.get("hub.verify_token") or ""), str(verify_token)):
        return params.get("hub.challenge") or ""
    return None


def firma_valida(cuerpo_bytes, cabecera, app_secret):
    """X-Hub-Signature-256 = 'sha256=' + HMAC(app_secret, cuerpo). Sin app_secret no se acepta nada."""
    if not app_secret or not cabecera or not cabecera.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode("utf-8"), cuerpo_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera[7:])


def extraer_mensajes(payload):
    """[(telefono, texto, id_mensaje)] de los mensajes de TEXTO entrantes. Otros tipos (audio, foto) -> texto
    indicativo para que se le pase al PEM."""
    out = []
    for e in (payload or {}).get("entry") or []:
        for ch in e.get("changes") or []:
            v = ch.get("value") or {}
            for m in v.get("messages") or []:
                tipo = m.get("type")
                if tipo == "text":
                    texto = (m.get("text") or {}).get("body") or ""
                elif tipo == "button":
                    texto = (m.get("button") or {}).get("text") or ""
                elif tipo == "interactive":
                    i = m.get("interactive") or {}
                    texto = ((i.get("button_reply") or i.get("list_reply") or {}).get("title")) or ""
                else:
                    texto = "[el técnico envió un %s]" % (tipo or "mensaje")
                if m.get("from"):
                    out.append((m["from"], texto, m.get("id", "")))
    return out


# ---------------------------------------------------------------------------------------------- envio
class Cliente:
    def __init__(self, config, timeout=15):
        self.c, self.timeout = config, timeout

    def _post(self, cuerpo):
        req = urllib.request.Request(
            "%s/%s/messages" % (API, self.c["phone_number_id"]), method="POST",
            data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.c["token"], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8")).get("error", {})
                msg = "%s (codigo %s)" % (err.get("message"), err.get("code"))
            except Exception:
                msg = str(e)
            raise RuntimeError("WhatsApp rechazo el mensaje: " + msg)

    def enviar(self, tel, texto):
        return self._post({"messaging_product": "whatsapp", "to": tel, "type": "text",
                           "text": {"body": texto[:4000], "preview_url": False}})

    def enviar_plantilla(self, tel, nombre, idioma="es", parametros=()):
        cuerpo = {"messaging_product": "whatsapp", "to": tel, "type": "template",
                  "template": {"name": nombre, "language": {"code": idioma}}}
        if parametros:
            cuerpo["template"]["components"] = [{"type": "body", "parameters": [
                {"type": "text", "text": str(p)} for p in parametros]}]
        return self._post(cuerpo)


class Consola:
    """Transporte de prueba: no envia nada; anota cada mensaje en whatsapp_salida.jsonl y lo muestra."""

    def __init__(self, carpeta, log=print):
        self.ruta, self.log = os.path.join(carpeta, "whatsapp_salida.jsonl"), log

    def enviar(self, tel, texto):
        from datetime import datetime
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps({"hora": datetime.now().isoformat(timespec="seconds"), "a": tel, "texto": texto},
                               ensure_ascii=False) + "\n")
        self.log("   [whatsapp simulado] a ...%s: %s" % (tel[-4:], texto.replace("\n", " / ")[:160]))
