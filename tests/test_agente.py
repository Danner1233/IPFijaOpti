# -*- coding: utf-8 -*-
"""Agente del tecnico: barreras en codigo (no inventa IPs, solo su caso, la IA solo clasifica)."""
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_ag_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import agente as A, reparto as R  # noqa: E402

T0 = datetime(2026, 11, 17, 10, 0, 0)
IP_RE = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")


def item(id_, cel="300 123 4567", tecnico="JUAN PEREZ"):
    return {"ID": id_, "Created": "2026-11-17T12:00:00Z", "PEM_ASIGNADO": "", "Est_Seg": "", "field_1": "64192718",
            "field_2": "CLIENTE SECRETO", "ActivApoyo": "", "field_15": tecnico, "field_16": cel}


def estado_con_caso(id_=777, **kw):
    e = R.nuevo_estado()
    R.agregar_pem(e, "Ana Uno")
    R.registrar_asignacion(e, item(id_, **kw), "Ana Uno", T0)
    return e


class PruebasTelefono(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(A.telefono("300 123 4567"), "573001234567")
        self.assertEqual(A.telefono("+57 300-123-4567"), "573001234567")
        self.assertEqual(A.telefono("573001234567"), "573001234567")
        self.assertEqual(A.telefono(""), "")


class PruebasAgente(unittest.TestCase):
    def test_aviso_al_asignar(self):
        e = estado_con_caso()
        [(tel, t)] = A.al_asignar(e, "777", T0)
        self.assertEqual(tel, "573001234567")
        self.assertIn("Juan", t)
        self.assertIn("777", t)
        self.assertNotIn("CLIENTE SECRETO", t)

    def test_sin_celular_no_envia(self):
        e = estado_con_caso(cel="")
        self.assertEqual(A.al_asignar(e, "777", T0), [])

    def test_numero_desconocido(self):
        e = estado_con_caso()
        [(tel, t)] = A.mensaje_tecnico(e, "573009999999", "hola", T0)
        self.assertIn("No encuentro", t)
        self.assertNotIn("777", t, "no revela casos de otros")

    def test_pide_ip_antes_de_que_el_pem_la_envie_no_inventa(self):
        e = estado_con_caso()
        [(_, t)] = A.mensaje_tecnico(e, "3001234567", "me pasas la IP?", T0)
        self.assertIn("todavía no", t)
        self.assertIsNone(IP_RE.search(t))
        self.assertEqual(len(e["asignaciones"]["777"]["para_pem"]), 1, "se le avisa al PEM")

    def test_ip_la_inventa_la_ia_no_importa_se_envia_lo_del_pem_literal(self):
        e = estado_con_caso()
        literal = "IP 10.20.30.40 /29\nGW 10.20.30.41"
        [(tel, t)] = A.mensaje_pem(e, "777", "Ana Uno", literal, "direccionamiento", T0)
        self.assertIn(literal, t)
        ia_mentirosa = lambda texto, esp: "direccionamiento"
        [(_, t2)] = A.mensaje_tecnico(e, "3001234567", "cual es la ip", T0, clasificar=ia_mentirosa)
        self.assertIn(literal, t2)
        self.assertEqual(set(m.group(0) for m in IP_RE.finditer(t2)), {"10.20.30.40", "10.20.30.41"})

    def test_ia_con_respuesta_fuera_de_lista_usa_reglas(self):
        e = estado_con_caso()
        [(_, t)] = A.mensaje_tecnico(e, "3001234567", "como va?", T0,
                                     clasificar=lambda t, x: "Claro, tu IP es 1.2.3.4")
        self.assertIn("en proceso", t)
        self.assertIsNone(IP_RE.search(t))

    def test_ia_que_falla_usa_reglas(self):
        def rota(t, x):
            raise TimeoutError("sin red")
        e = estado_con_caso()
        [(_, t)] = A.mensaje_tecnico(e, "3001234567", "estado?", T0, clasificar=rota)
        self.assertIn("en proceso", t)

    def test_otra_cosa_se_le_pasa_al_pem(self):
        e = estado_con_caso()
        A.mensaje_tecnico(e, "3001234567", "la ONT tiene la luz LOS en rojo", T0)
        self.assertEqual(e["asignaciones"]["777"]["para_pem"][0]["texto"], "la ONT tiene la luz LOS en rojo")

    def test_pem_ajeno_no_puede_escribir(self):
        e = estado_con_caso()
        R.agregar_pem(e, "Beto Dos")
        with self.assertRaises(ValueError):
            A.mensaje_pem(e, "777", "Beto Dos", "hola", "mensaje", T0)

    def test_cierre_exitoso_pide_confirmacion_si_y_no(self):
        e = estado_con_caso()
        R.latido(e, "Ana Uno", True, {"777": "Exitosa"}, T0)
        [(_, t)] = A.al_documentar(e, "777", "Exitosa", T0)
        self.assertIn("SI o NO", t)
        self.assertEqual(A.al_documentar(e, "777", "Exitosa", T0), [], "se avisa una sola vez")
        [(_, r)] = A.mensaje_tecnico(e, "3001234567", "Sí, todo bien", T0 + timedelta(minutes=5))
        self.assertIn("Gracias", r)
        self.assertEqual(e["asignaciones"]["777"]["confirmacion_tecnico"], "si")

    def test_cierre_y_responde_no(self):
        e = estado_con_caso()
        R.latido(e, "Ana Uno", True, {"777": "Exitosa"}, T0)
        A.al_documentar(e, "777", "Exitosa", T0)
        A.mensaje_tecnico(e, "3001234567", "no, no navega", T0)
        a = e["asignaciones"]["777"]
        self.assertEqual(a["confirmacion_tecnico"], "no")
        self.assertEqual(a["para_pem"][-1]["texto"], "no, no navega")

    def test_si_sin_pregunta_no_es_confirmacion(self):
        e = estado_con_caso()
        A.mensaje_tecnico(e, "3001234567", "si", T0)
        self.assertNotIn("confirmacion_tecnico", e["asignaciones"]["777"])

    def test_caso_cerrado_hace_mucho_ya_no_responde(self):
        e = estado_con_caso()
        R.latido(e, "Ana Uno", True, {"777": "Exitosa"}, T0)
        [(_, t)] = A.mensaje_tecnico(e, "3001234567", "hola", T0 + timedelta(hours=A.HORAS_CHAT + 1))
        self.assertIn("No encuentro", t)

    def test_responder_limpia_lo_pendiente_y_queda_historial(self):
        e = estado_con_caso()
        A.mensaje_tecnico(e, "3001234567", "necesito ayuda con la ONT", T0)
        A.mensaje_pem(e, "777", "Ana Uno", "Reinicia la ONT y me confirmas", "mensaje", T0)
        a = e["asignaciones"]["777"]
        self.assertEqual(a["para_pem"], [])
        self.assertEqual([m["de"] for m in a["chat"]], ["tecnico", "agente", "pem"])

    def test_reglas(self):
        self.assertEqual(A.clasificar_reglas("buenas tardes"), "saludo")
        self.assertEqual(A.clasificar_reglas("me regalas el gateway"), "direccionamiento")
        self.assertEqual(A.clasificar_reglas("como va mi caso"), "estado")
        self.assertEqual(A.clasificar_reglas("no quedó", True), "confirmar_no")
        self.assertEqual(A.clasificar_reglas("listo, gracias", True), "confirmar_si")


if __name__ == "__main__":
    unittest.main()
