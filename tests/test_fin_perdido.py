# -*- coding: utf-8 -*-
"""La ventana no se queda pegada en «Verificando y cerrando» si no alcanzo a leer el final del script."""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_fp_"))
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import hac_zac_gui as gui  # noqa: E402

FIN = {"seq": 40, "fase": "fin", "paso": 7, "resultado": {"solicitud_id": "65079", "rr": "64767642"}}


class PruebasFinalPerdido(unittest.TestCase):
    def test_recupera_el_final_que_no_vio(self):
        e = {"seq": 43, "fase": "esperando", "ultimo": FIN}
        self.assertEqual(gui.final_perdido(e, True, None), FIN)

    def test_no_lo_aplica_dos_veces(self):
        e = {"seq": 45, "fase": "esperando", "ultimo": FIN}
        self.assertIsNone(gui.final_perdido(e, True, 40))

    def test_sin_proceso_en_curso_no_hace_nada(self):
        e = {"seq": 43, "fase": "esperando", "ultimo": FIN}
        self.assertIsNone(gui.final_perdido(e, False, None), "al abrir la ventana no repite el resultado viejo")

    def test_esperando_de_una_solicitud_nueva_no_hace_nada(self):
        self.assertIsNone(gui.final_perdido({"seq": 50, "fase": "esperando", "ultimo": None}, True, 40))

    def test_script_viejo_avisa_y_libera(self):
        r = gui.final_perdido({"seq": 43, "fase": "esperando", "log": []}, True, None, 7)
        self.assertEqual((r["fase"], r["paso"]), ("error", 7))
        self.assertIn("SecureCRT", r["error"])

    def test_otras_fases_no(self):
        self.assertIsNone(gui.final_perdido({"seq": 9, "fase": "corriendo"}, True, None))


class PruebasScript(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
            self.src = f.read()

    def test_envia_ultimo_y_copia_el_resultado(self):
        self.assertIn('"ultimo": self.ultimo', self.src)
        # RES se vacia en nuevo_ciclo: el ultimo final debe llevar una copia
        self.assertIn("dict(self.resultado)", self.src)
        self.assertLess(self.src.index("self.ultimo = {"), self.src.index("RES.clear()"))

    def test_lo_olvida_al_tomar_otra_solicitud(self):
        i = self.src.index("def esperar_solicitud")
        self.assertIn("self.ultimo = None", self.src[i:i + 1500])


if __name__ == "__main__":
    unittest.main()
