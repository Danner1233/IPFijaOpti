# -*- coding: utf-8 -*-
"""Estados y causas hacia SharePoint: valores exactos, causa en su columna, observacion agregada y liberar."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_est_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sp_lector  # noqa: E402
from hac_zac import causas, cola, estados  # noqa: E402

T = datetime(2026, 11, 17, 16, 50)
COL_NO, COL_ESC = "Causa_x0020_No_x0020_Exitosa", "Causa_x0020_Escalamiento"


class PruebasCatalogo(unittest.TestCase):
    def test_cantidades_de_la_tabla(self):
        self.assertEqual(len(causas.para(estados.ESCALAMIENTO)), 13)
        self.assertEqual(len(causas.para(estados.NO_EXITOSA)), 18)
        self.assertEqual(causas.para(estados.EXITOSA), [])

    def test_filtra_por_red_y_deja_las_generales(self):
        atp = [c["causa"] for c in causas.para(estados.NO_EXITOSA, "ATP")]
        self.assertIn("ATP No Responde a PING", atp)
        self.assertIn("Cliente no puede esperar", atp, "las generales salen en todas las redes")
        self.assertNotIn("ONNET No Responde a PING", atp)
        self.assertNotIn("Claro Falla Posterior a 24Hrs", atp)
        claro = [c["causa"] for c in causas.para(estados.ESCALAMIENTO, "CLARO")]
        self.assertIn("Red Propia ONT No Sincronizada", claro)
        self.assertNotIn("ONNET ONT No Sincronizada", claro)

    def test_datos_de_una_causa(self):
        c = causas.buscar(estados.NO_EXITOSA, "Cliente Cancela IP Fija")
        self.assertEqual((c["notifica"], c["escala"]), ("PEM", ""))
        self.assertIn("CCOT", c["accion"])


class PruebasValoresSharePoint(unittest.TestCase):
    def test_est_seg_exacto(self):
        self.assertEqual(estados.a_sp("No exitosa"), "No Exitosa")
        self.assertEqual(estados.a_sp("Exitosa"), "Exitosa")
        self.assertEqual(estados.a_sp("escalamiento"), "Escalamiento")
        self.assertEqual(estados.a_sp("Sin Asignar"), "Sin Asignar")

    def test_no_exitosa_con_causa_y_observacion(self):
        campos, nota, cols = sp_lector.cambios_estado("No exitosa", "ATP No Responde a PING", "Se llamo a NOC",
                                                      "Danner Arias", T)
        self.assertEqual(campos, {"Est_Seg": "No Exitosa", COL_NO: "ATP No Responde a PING", COL_ESC: None})
        self.assertEqual(cols, [COL_NO])
        self.assertEqual(nota, "[17/11 16:50] PEM Danner Arias: No Exitosa · ATP No Responde a PING — Se llamo a NOC")

    def test_escalamiento_limpia_la_causa_de_no_exitosa(self):
        campos, _, cols = sp_lector.cambios_estado("Escalamiento", "Falla Gestor ACS Friendly", "", "A", T)
        self.assertEqual(campos[COL_ESC], "Falla Gestor ACS Friendly")
        self.assertIsNone(campos[COL_NO])

    def test_exitosa_limpia_causas_y_sin_observacion_no_escribe_nota(self):
        campos, nota, cols = sp_lector.cambios_estado("Exitosa")
        self.assertEqual(campos, {"Est_Seg": "Exitosa", COL_NO: None, COL_ESC: None})
        self.assertEqual((nota, cols), ("", []))


class Driver:
    """Simula SharePoint: guarda lo que recibe y responde como la funcion JS."""

    def __init__(self, respuesta):
        self.respuesta, self.llamadas = respuesta, []

    def execute_async_script(self, js, *args):
        self.llamadas.append((js, args))
        return self.respuesta


class PruebasEnvio(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_env_")})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_envia_estado_causa_y_nota(self):
        cola.pedir_estado_sp("64900", "No exitosa", "Solicitud Duplicada", "Ya existe la 64899", "Ana")
        d = Driver({"ok": True, "antes": "Asignada"})
        self.assertEqual(sp_lector.enviar_estados_pendientes(d), 1)
        js, args = d.llamadas[0]
        self.assertIs(js, sp_lector.JS_ESTADO)
        _, _, id_, campos, nota, cols, causa = args
        self.assertEqual((id_, campos["Est_Seg"], campos[COL_NO], causa), ("64900", "No Exitosa",
                                                                         "Solicitud Duplicada", "Solicitud Duplicada"))
        self.assertIn("Ya existe la 64899", nota)
        self.assertEqual(cola.pendientes_sp_detalle(), {}, "quedo escrito")
        reg = cola.leer_registro_sp()[-1]
        self.assertEqual((reg["antes"], reg["despues"], reg["causa"]), ("Asignada", "No Exitosa", "Solicitud Duplicada"))

    def test_si_falla_queda_pendiente(self):
        cola.pedir_estado_sp("64901", "Exitosa")
        sp_lector.enviar_estados_pendientes(Driver({"ok": False, "motivo": "412"}))
        self.assertIn("64901", cola.pendientes_sp_detalle())

    def test_liberar_y_no_volver_a_tomarla(self):
        it = {"ID": 64902, "PEM_ASIGNADO": "", "Est_Seg": "Sin Asignar", "Created": "2026-11-17T10:00:00Z",
              "ActivApoyo": "No"}
        otra = dict(it, ID=64903, Created="2026-11-17T11:00:00Z")
        cola.registrar_mia({"id": "64902", "rr": "1"}, "Ana")
        cola.pedir_liberar("64902", "Ana")
        self.assertEqual(cola.solicitudes()[0]["estado"], "liberada")
        d = Driver({"ok": True, "antes": "Asignada"})
        self.assertEqual(sp_lector.enviar_liberaciones(d), 1)
        self.assertEqual(d.llamadas[0][1][2:], ("64902", "Ana"))
        self.assertEqual(cola.liberar_pendientes(), {})
        self.assertEqual(cola.elegir_libre([it, otra])["ID"], 64903, "no se retoma la que libere")

    def test_liberar_que_ya_no_es_mia_avisa(self):
        cola.pedir_liberar("64904", "Ana")
        sp_lector.enviar_liberaciones(Driver({"ok": False, "motivo": "ya no esta asignada a usted (PEM: Beto)"}))
        self.assertIn("64904", cola.liberar_pendientes(), "se reintenta (y queda en el registro)")
        self.assertFalse(cola.leer_registro_sp()[-1]["ok"])


class PruebasCierreSinForms(unittest.TestCase):
    """No exitosa / Escalamiento no van a Forms: se cierran y se envian a SharePoint."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_cie_")})
        self.env.start()
        from hac_zac.servicio import Servicio
        self.sv = Servicio()
        self.sv.store.guardar({"id": "70030", "rr": "1", "creada": "2026-11-17T16:00:00"})
        cola.registrar_mia({"id": "70030", "rr": "1"}, "Ana")

    def tearDown(self):
        self.env.stop()

    def test_cerrar_no_exitosa(self):
        self.sv.aplicar_resultado("70030", "No exitosa", "Solicitud Duplicada", "obs")
        self.assertEqual(cola.pendientes_sp_detalle(), {}, "aplicar solo no envia (aun abierta)")
        rec = self.sv.cerrar_sin_forms("70030")
        self.assertTrue(rec["cerrada_en"])
        self.assertEqual(rec["estado"], "Cerrada en SharePoint")
        p = cola.pendientes_sp_detalle()["70030"]
        self.assertEqual((p["est_seg"], p["causa"], p["observacion"]), ("No exitosa", "Solicitud Duplicada", "obs"))
        self.assertEqual(cola.solicitudes()[0]["estado"], "terminada", "queda libre para tomar otra")

    def test_exitosa_no_se_cierra_sin_forms(self):
        self.sv.aplicar_resultado("70030", "Exitosa")
        self.assertIsNone(self.sv.cerrar_sin_forms("70030"))

    def test_cambio_despues_de_cerrada_se_reenvia(self):
        self.sv.aplicar_resultado("70030", "Escalamiento", "Falla Gestor ACS Friendly", "")
        self.sv.cerrar_sin_forms("70030")
        cola.resultado_sp("70030", True)
        self.sv.aplicar_resultado("70030", "No exitosa", "Cliente no puede esperar", "cambio")
        self.assertEqual(cola.pendientes_sp_detalle()["70030"]["causa"], "Cliente no puede esperar")

    def test_el_tiempo_para_al_cerrar(self):
        from hac_zac import tiempos
        rec = {"creada": "2026-11-17T16:00:00", "cerrada_en": "2026-11-17T16:10:00"}
        m = tiempos.medir(rec, None, datetime(2026, 11, 17, 18, 0))
        self.assertEqual(int(m["minutos"]), 10)


if __name__ == "__main__":
    unittest.main()
