# -*- coding: utf-8 -*-
"""Pausa del PEM (razon opcional + tiempo), configurador configurable y espera del lector de Outlook."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_pa_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import presencia, reparto_equipo  # noqa: E402
from hac_zac.servicio import configurador_de  # noqa: E402

AHORA = datetime(2026, 11, 18, 12, 0, 0)


class PruebasPausa(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_pa_d_")})
        self.env.start()
        self.eq = tempfile.mkdtemp(prefix="hz_pa_e_")

    def tearDown(self):
        self.env.stop()

    def test_poner_vence_y_quitar(self):
        p = presencia.poner_pausa(30, "  Almuerzo  ", AHORA)
        self.assertEqual(p["razon"], "Almuerzo")
        self.assertTrue(presencia.mi_pausa(AHORA + timedelta(minutes=29)))
        self.assertIsNone(presencia.mi_pausa(AHORA + timedelta(minutes=30)), "al cumplirse vuelve sola")
        presencia.poner_pausa(60, "", AHORA)
        presencia.quitar_pausa()
        self.assertIsNone(presencia.mi_pausa(AHORA))

    def test_el_admin_la_ve_y_no_le_reparte(self):
        pausa = presencia.poner_pausa(60, "Almuerzo", AHORA)
        presencia.publicar(self.eq, "Juan Gutierrez", AHORA, False, AHORA, pausa=pausa)
        presencia.publicar(self.eq, "Danner Arias", AHORA, False, AHORA)
        filas = {f["nombre"]: f for f in presencia.equipo(self.eq, AHORA + timedelta(minutes=1))}
        self.assertEqual(filas["Juan Gutierrez"]["estado"], "pausa")
        self.assertEqual(presencia.texto_pausa(filas["Juan Gutierrez"]["pausa"]), "⏸ En pausa: Almuerzo (hasta 13:00)")
        roster = [{"nombre": "Juan Gutierrez", "activo": True, "ultimo": ""},
                  {"nombre": "Danner Arias", "activo": True, "ultimo": "2026-11-18T11:00:00"}]
        it = {"ID": 1, "Created": "2026-11-18T16:50:00Z", "PEM_ASIGNADO": "", "Est_Seg": "Sin Asignar",
              "ActivApoyo": "No", "Observaciones": ""}
        pres = reparto_equipo.presencia_por_nombre(self.eq, AHORA + timedelta(minutes=1))
        self.assertEqual([n for _, n in reparto_equipo.plan([it], roster, pres, AHORA)], ["Danner Arias"])

    def test_pausa_vencida_en_el_archivo_cuenta_como_en_linea(self):
        pausa = presencia.poner_pausa(15, "Baño", AHORA)
        presencia.publicar(self.eq, "Juan Gutierrez", AHORA + timedelta(minutes=14), False,
                           AHORA + timedelta(minutes=14), pausa=pausa)
        f = presencia.equipo(self.eq, AHORA + timedelta(minutes=16))[0]
        self.assertEqual((f["estado"], f["pausa"]), ("en_linea", None))


class PruebasConfigurador(unittest.TestCase):
    def test_vacio_usa_el_nombre_de_sharepoint(self):
        self.assertEqual(configurador_de({"configurador": "", "pem_nombre": "Juan Gutierrez"}), "JUAN GUTIERREZ")

    def test_el_viejo_valor_fijo_no_le_queda_a_otro_pem(self):
        self.assertEqual(configurador_de({"configurador": "DANNER ARIAS", "pem_nombre": "Juan Gutierrez"}),
                         "JUAN GUTIERREZ")
        self.assertEqual(configurador_de({"configurador": "DANNER ARIAS", "pem_nombre": "Danner Arias"}),
                         "DANNER ARIAS")

    def test_el_que_escribe_manda(self):
        self.assertEqual(configurador_de({"configurador": "j. gutierrez sena", "pem_nombre": "Juan"}),
                         "J. GUTIERREZ SENA")


class PruebasEsperaCorreo(unittest.TestCase):
    def setUp(self):
        import correo_lector
        self.C = correo_lector

    def test_con_pendientes_espera_poco(self):
        self.assertEqual(self.C.espera_siguiente(lambda: {"1": {}}, dormir=lambda s: None), self.C.RAPIDO_S)

    def test_sin_pendientes_espera_el_minuto(self):
        self.assertEqual(self.C.espera_siguiente(lambda: {}, dormir=lambda s: None), self.C.CADA_S)

    def test_si_llega_una_nueva_busca_de_una(self):
        llamadas = iter([{}, {}, {"1": {}}])
        t = self.C.espera_siguiente(lambda: next(llamadas, {"1": {}}), dormir=lambda s: None)
        self.assertEqual(t, 2 * self.C.PASO_S)


if __name__ == "__main__":
    unittest.main()
