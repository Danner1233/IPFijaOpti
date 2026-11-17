# -*- coding: utf-8 -*-
"""Servidor central + cliente del PEM, de punta a punta por HTTP (sin SharePoint)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_cen_"))
import servidor_central as S  # noqa: E402
from hac_zac import central_cliente as CC, cola  # noqa: E402


def item(id_, creada="2026-11-17T12:00:00Z", pem="", est=""):
    return {"ID": id_, "Created": creada, "PEM_ASIGNADO": pem, "Est_Seg": est, "field_1": "64192718",
            "field_2": "Cliente %d" % id_, "ActivApoyo": "", "field_15": "Tecnico X", "field_16": "3001234567"}


class PruebasCentralHTTP(unittest.TestCase):
    def setUp(self):
        self.dir_central = tempfile.mkdtemp(prefix="hz_central_")
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": self.dir_central})
        self.env.start()
        self.c = S.Central(self.dir_central)
        self.tok_ana = self.c.R.agregar_pem(self.c.estado, "Ana Uno")
        self.tok_beto = self.c.R.agregar_pem(self.c.estado, "Beto Dos")
        self.srv = S.crear_servidor(self.c, puerto=0, host="127.0.0.1")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()

    def test_token_invalido(self):
        with self.assertRaises(ConnectionError) as e:
            CC.enviar_latido(self.url, "malo", True, {})
        self.assertIn("Token", str(e.exception))

    def test_sin_servidor_mensaje_claro(self):
        with self.assertRaises(ConnectionError) as e:
            CC.enviar_latido("http://127.0.0.1:1", self.tok_ana, True, {}, timeout=2)
        self.assertIn("Sin conexion", str(e.exception))

    def test_flujo_completo(self):
        # 1) Ana disponible, Beto no: solo Ana recibe
        CC.enviar_latido(self.url, self.tok_ana, True, {})
        CC.enviar_latido(self.url, self.tok_beto, False, {})
        asignadas = []
        hechas = self.c.repartir([item(1), item(2)], lambda it, n: asignadas.append((it["ID"], n)) or True,
                                 log=lambda m: None)
        self.assertEqual(hechas, [("1", "Ana Uno")])
        # 2) el latido le entrega su caso con los datos de SharePoint (tecnico y celular incluidos)
        r = CC.enviar_latido(self.url, self.tok_ana, True, {})
        self.assertEqual(r["pem"], "Ana Uno")
        self.assertEqual([c["id"] for c in r["casos"]], ["1"])
        self.assertEqual(r["casos"][0]["celular_tecnico"], "3001234567")
        # 3) Ana ocupada: no recibe la 2 aunque siga disponible
        self.assertEqual(self.c.repartir([item(1, pem="Ana Uno", est="Asignada"), item(2)], lambda *a: True,
                                         log=lambda m: None), [])
        # 4) documenta: el central encola el Est_Seg y Ana queda libre
        r = CC.enviar_latido(self.url, self.tok_ana, True, {"1": "Exitosa"})
        self.assertEqual(r["casos"], [])
        self.assertEqual(r["confirmadas"], [])                       # todavia no escrito en SharePoint
        self.assertEqual(cola.pendientes_sp(), {"1": "Exitosa"})
        # repetir el reporte no lo vuelve a encolar
        CC.enviar_latido(self.url, self.tok_ana, True, {"1": "Exitosa"})
        self.assertEqual(cola.estados_sp()["1"]["intentos"], 0)
        # 5) el ciclo de SharePoint lo escribe -> el siguiente latido lo confirma
        cola.resultado_sp("1", True)
        r = CC.enviar_latido(self.url, self.tok_ana, True, {"1": "Exitosa"})
        self.assertEqual(r["confirmadas"], ["1"])
        # 6) ya libre: recibe la 2
        self.assertEqual(self.c.repartir([item(1, pem="Ana Uno", est="Asignada"), item(2)], lambda *a: True,
                                         log=lambda m: None), [("2", "Ana Uno")])
        # 7) el estado queda en disco
        with open(os.path.join(self.dir_central, "central.json"), encoding="utf-8") as f:
            self.assertIn("2", json.load(f)["asignaciones"])

    def test_si_sharepoint_rechaza_no_se_registra(self):
        CC.enviar_latido(self.url, self.tok_ana, True, {})
        self.assertEqual(self.c.repartir([item(5)], lambda it, n: False, log=lambda m: None), [])
        self.assertEqual(self.c.estado["asignaciones"], {})

    def test_simulacion_no_asigna(self):
        self.c.simular = True
        CC.enviar_latido(self.url, self.tok_ana, True, {})
        llamadas, log = [], []
        self.assertEqual(self.c.repartir([item(1)], lambda *a: llamadas.append(a) or True, log=log.append), [])
        self.assertEqual(llamadas, [])
        self.assertIn("simulacion", log[0])

    def test_ruta_desconocida_y_json_malo(self):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(self.url + "/latido", data=b"{no json", method="POST",
                                     headers={"Authorization": "Bearer " + self.tok_ana})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 400)
        e.exception.close()
        with urllib.request.urlopen(self.url + "/salud", timeout=5) as r:
            self.assertTrue(json.loads(r.read())["ok"])


class PruebasClientePEM(unittest.TestCase):
    """Lado del PEM: su propia carpeta de datos."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_pem_")})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_caso_recibido_queda_en_mi_cola_y_su_estado_va_al_central(self):
        d = cola.desde_sp(item(7))
        nuevos = CC.aplicar_respuesta({"pem": "Ana Uno", "casos": [d], "confirmadas": []})
        self.assertEqual(nuevos, ["7"])
        self.assertEqual(CC.aplicar_respuesta({"pem": "Ana Uno", "casos": [d]}), [], "no se duplica")
        s = cola.solicitudes()[0]
        self.assertEqual((s["estado"], s["origen"], s["asignado"]), ("asignada", "central", "Ana Uno"))
        self.assertIn("SOLICITUD ID: 7", s["datos"]["txt_sol"])
        self.assertIn("64192718", cola.pendientes_correo(), "el lector de correo la busca por su RR")
        # documentar -> se reporta al central, no al lector local de SharePoint
        cola.pedir_estado_sp("7", "Exitosa")
        cola.pedir_estado_sp("99", "Exitosa")             # una que no vino del central
        self.assertEqual(CC.documentadas_para_central(), {"7": "Exitosa"})
        self.assertTrue(cola.es_del_central("7"))
        self.assertFalse(cola.es_del_central("99"))
        CC.aplicar_respuesta({"pem": "Ana Uno", "casos": [], "confirmadas": ["7"]})
        self.assertEqual(CC.documentadas_para_central(), {})

    def test_sin_configurar(self):
        self.assertFalse(CC.configurado({}))
        c = CC.Conexion({}, lambda e: None)
        self.assertFalse(c.latir_una_vez()["ok"])


if __name__ == "__main__":
    unittest.main()
