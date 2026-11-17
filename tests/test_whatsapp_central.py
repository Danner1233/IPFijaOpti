# -*- coding: utf-8 -*-
"""Fase 3: WhatsApp (firma de Meta, webhook), mensajes del PEM, avisos automaticos e IA."""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_wa_"))
import servidor_central as S  # noqa: E402
from hac_zac import central_cliente as CC, cola, ia, reparto as R, whatsapp as W  # noqa: E402

SECRETO = "secreto-de-prueba"


def item(id_, cel="3001234567"):
    return {"ID": id_, "Created": "2026-11-17T12:00:00Z", "PEM_ASIGNADO": "", "Est_Seg": "", "field_1": "64192718",
            "field_2": "CLIENTE", "ActivApoyo": "", "field_15": "JUAN PEREZ", "field_16": cel}


def payload(tel, texto):
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": tel, "id": "wamid.1", "type": "text", "text": {"body": texto}}]}}]}]}


class TransporteFalso:
    def __init__(self, cfg=None):
        self.c = cfg or {}
        self.textos, self.plantillas = [], []

    def enviar(self, tel, texto):
        self.textos.append((tel, texto))

    def enviar_plantilla(self, tel, nombre, idioma="es", parametros=()):
        self.plantillas.append((tel, nombre, idioma, tuple(parametros)))


class PruebasWhatsapp(unittest.TestCase):
    def test_firma(self):
        cuerpo = b'{"a":1}'
        f = "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
        self.assertTrue(W.firma_valida(cuerpo, f, SECRETO))
        self.assertFalse(W.firma_valida(cuerpo + b" ", f, SECRETO))
        self.assertFalse(W.firma_valida(cuerpo, f, ""))
        self.assertFalse(W.firma_valida(cuerpo, None, SECRETO))

    def test_verificacion_webhook(self):
        p = {"hub.mode": "subscribe", "hub.verify_token": "palabra", "hub.challenge": "123"}
        self.assertEqual(W.verificar_suscripcion(p, "palabra"), "123")
        self.assertIsNone(W.verificar_suscripcion(p, "otra"))
        self.assertIsNone(W.verificar_suscripcion(p, ""))

    def test_extraer(self):
        self.assertEqual(W.extraer_mensajes(payload("573001234567", "hola")), [("573001234567", "hola", "wamid.1")])
        audio = {"entry": [{"changes": [{"value": {"messages": [{"from": "57300", "type": "audio"}]}}]}]}
        self.assertIn("audio", W.extraer_mensajes(audio)[0][1])
        self.assertEqual(W.extraer_mensajes({"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}), [])

    def test_config_cifra_secretos(self):
        d = tempfile.mkdtemp()
        W.guardar_config(d, {"phone_number_id": "1", "token": "tok-123", "app_secret": "s", "verify_token": "v"})
        crudo = open(os.path.join(d, "whatsapp.json"), encoding="utf-8").read()
        self.assertNotIn("tok-123", crudo)
        self.assertEqual(W.cargar_config(d)["token"], "tok-123")


class PruebasIA(unittest.TestCase):
    def test_interpretar(self):
        self.assertEqual(ia.interpretar('{"intencion": "estado"}'), "estado")
        self.assertEqual(ia.interpretar('```json\n{"intencion": "otro"}\n```'), "otro")
        with self.assertRaises(ValueError):
            ia.interpretar("Tu IP es 10.0.0.1")
        with self.assertRaises(ValueError):
            ia.interpretar('{"intencion": "inventar_ip"}')

    def test_url(self):
        self.assertEqual(ia.url_chat("https://x.openai.azure.com/"), "https://x.openai.azure.com/openai/v1/chat/completions")
        self.assertTrue(ia.url_chat("https://x.openai.azure.com/openai/v1").endswith("/openai/v1/chat/completions"))


class PruebasCentralWhatsapp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hz_waC_")
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": self.dir})
        self.env.start()
        self.c = S.Central(self.dir)
        self.tok = R.agregar_pem(self.c.estado, "Ana Uno")
        self.wa = TransporteFalso()
        self.c.whatsapp = self.wa
        self.c.wa_config = {"verify_token": "palabra", "app_secret": SECRETO}
        self.srv = S.crear_servidor(self.c, puerto=0, host="127.0.0.1")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        CC.enviar_latido(self.url, self.tok, True, {})
        self.c.repartir([item(777)], lambda *a: True, log=lambda m: None)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()

    def _post_wa(self, cuerpo_dict, firmar=True):
        cuerpo = json.dumps(cuerpo_dict).encode()
        h = {"Content-Type": "application/json"}
        if firmar:
            h["X-Hub-Signature-256"] = "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
        req = urllib.request.Request(self.url + "/whatsapp", data=cuerpo, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def _esperar_respuestas(self, n):
        import time
        for _ in range(50):
            self.c.enviar_pendientes()
            if len(self.wa.textos) >= n:
                return
            time.sleep(0.05)

    def test_aviso_al_asignar(self):
        self.c.enviar_pendientes()
        self.assertEqual(self.wa.textos[0][0], "573001234567")
        self.assertIn("777", self.wa.textos[0][1])

    def test_primer_aviso_con_plantilla(self):
        self.wa.c = {"plantilla_inicio": "aviso_solicitud", "plantilla_idioma": "es_CO"}
        self.c.enviar_pendientes()
        self.assertEqual(self.wa.plantillas, [("573001234567", "aviso_solicitud", "es_CO", ("777",))])
        self.assertEqual(self.wa.textos, [])

    def test_webhook_sin_firma_o_firma_mala_se_rechaza(self):
        self.assertEqual(self._post_wa(payload("573001234567", "hola"), firmar=False), 403)
        self.assertNotIn("tecnico", [m["de"] for m in self.c.estado["asignaciones"]["777"]["chat"]])

    def test_webhook_verificacion_get(self):
        with urllib.request.urlopen(self.url + "/whatsapp?hub.mode=subscribe&hub.verify_token=palabra"
                                               "&hub.challenge=xyz", timeout=5) as r:
            self.assertEqual(r.read(), b"xyz")

    def test_conversacion_completa(self):
        self.c.enviar_pendientes()                                    # aviso de asignacion
        self.assertEqual(self._post_wa(payload("573001234567", "me pasas la ip")), 200)
        self._esperar_respuestas(2)
        self.assertIn("todavía no", self.wa.textos[1][1])
        # el PEM ve la pregunta en su latido
        r = CC.enviar_latido(self.url, self.tok, True, {})
        caso = r["casos"][0]
        self.assertEqual(caso["_para_pem"][0]["texto"], "me pasas la ip")
        # responde con el direccionamiento desde su aplicacion (POST /mensaje)
        with mock.patch.object(CC, "config", return_value=(self.url, self.tok)):
            self.assertTrue(CC.enviar_mensaje({}, "777", "IP 10.1.1.10/30 GW 10.1.1.9", "direccionamiento")["ok"])
        self.c.enviar_pendientes()
        self.assertIn("IP 10.1.1.10/30 GW 10.1.1.9", self.wa.textos[2][1])
        # documenta Exitosa -> el agente pregunta al tecnico si quedo en orden
        CC.enviar_latido(self.url, self.tok, True, {"777": "Exitosa"})
        self.c.enviar_pendientes()
        self.assertIn("SI o NO", self.wa.textos[3][1])
        self._post_wa(payload("573001234567", "si señor, navegando"))
        self._esperar_respuestas(5)
        self.assertIn("Gracias", self.wa.textos[4][1])
        self.assertEqual(self.c.estado["asignaciones"]["777"]["confirmacion_tecnico"], "si")

    def test_pem_no_puede_escribir_a_caso_ajeno(self):
        tok_b = R.agregar_pem(self.c.estado, "Beto Dos")
        with mock.patch.object(CC, "config", return_value=(self.url, tok_b)):
            with self.assertRaises(ConnectionError) as e:
                CC.enviar_mensaje({}, "777", "hola", "mensaje")
        self.assertIn("no está asignado", str(e.exception))

    def test_simulador_solo_desde_este_pc_y_sin_secreto(self):
        self.c.wa_config, self.c.wa_simulado = None, True
        self.assertEqual(self._post_wa(payload("573001234567", "hola"), firmar=False), 200)

    def test_cliente_guarda_la_conversacion_y_avisa_preguntas(self):
        self._post_wa(payload("573001234567", "la ONT no enciende"))
        self._esperar_respuestas(2)
        r = CC.enviar_latido(self.url, self.tok, True, {})
        with mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_waP_")}):
            CC.aplicar_respuesta(r)
            self.assertEqual(CC.aplicar_respuesta.preguntas, ["777"])
            s = cola.solicitudes()[0]
            self.assertEqual(s["para_pem"][0]["texto"], "la ONT no enciende")
            self.assertNotIn("_chat", s["datos"])
            CC.aplicar_respuesta(r)
            self.assertEqual(CC.aplicar_respuesta.preguntas, [], "no avisa dos veces lo mismo")


class PruebasEnvioRobusto(unittest.TestCase):
    def test_reintenta_y_no_se_cae(self):
        c = S.Central(tempfile.mkdtemp())
        llamadas = []

        class Falla:
            c = {}

            def enviar(self, tel, texto):
                llamadas.append(1)
                raise RuntimeError("caido")
        c.whatsapp = Falla()
        c._encolar([("573001234567", "x")])
        with mock.patch.object(S.time, "sleep", lambda s: None):
            self.assertEqual(c.enviar_pendientes(log=lambda m: None), 0)
        self.assertEqual(len(llamadas), 3)


if __name__ == "__main__":
    unittest.main()
