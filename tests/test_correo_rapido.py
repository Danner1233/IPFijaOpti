# -*- coding: utf-8 -*-
"""Correo y SharePoint mas rapidos: tiempos y no volver a abrir correos de otra solicitud."""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_cr_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import correo_lector as C  # noqa: E402
import sp_lector  # noqa: E402


class PruebasTiempos(unittest.TestCase):
    def test_valores(self):
        self.assertEqual(sp_lector.CADA_S, 6)
        self.assertEqual(C.RAPIDO_S, 5)
        self.assertEqual(C.espera_siguiente(lambda: {"1": {}}, dormir=lambda s: None), 5)


class PruebasYaVistos(unittest.TestCase):
    def setUp(self):
        C.YA_VISTOS.clear()

    def test_solo_recuerda_los_de_otra_solicitud(self):
        C.marcar_visto("64950", "correo A", "SOLICITUD ID: 64900\nCUENTA RR: 1")
        C.marcar_visto("64950", "correo B", "")                      # no se pudo leer: se reintenta
        C.marcar_visto("64950", "correo C", "SOLICITUD ID: 64950")   # es la buscada: no se marca
        self.assertTrue(C.ya_visto("64950", "correo A"))
        self.assertFalse(C.ya_visto("64950", "correo B"))
        self.assertFalse(C.ya_visto("64950", "correo C"))
        self.assertFalse(C.ya_visto("64951", "correo A"), "por solicitud")

    def test_no_reabre_y_encuentra_el_nuevo(self):
        abiertos = []
        bandeja = [("viejo", "SOLICITUD ID: 64900")]

        def leer(i, sol_id="64950"):
            etiqueta, texto = bandeja[i]
            if C.ya_visto(sol_id, etiqueta):
                return "", None
            abiertos.append(etiqueta)
            C.marcar_visto(sol_id, etiqueta, texto)
            return texto, None

        self.assertIsNone(C.elegir_correo("64950", len(bandeja), leer, log=lambda m: None))
        bandeja.insert(0, ("nuevo", "SOLICITUD ID: 64950\nplantilla"))
        self.assertEqual(C.elegir_correo("64950", len(bandeja), leer, log=lambda m: None)[0],
                         "SOLICITUD ID: 64950\nplantilla")
        self.assertEqual(abiertos, ["viejo", "nuevo"], "el viejo se abrio una sola vez")


if __name__ == "__main__":
    unittest.main()
