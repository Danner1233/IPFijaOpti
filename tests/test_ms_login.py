# -*- coding: utf-8 -*-
"""Prueba del flujo de inicio de sesion con un navegador simulado (no toca Microsoft)."""
import os
import sys
import tempfile
import unittest

os.environ["HAC_ZAC_DATOS"] = tempfile.mkdtemp(prefix="hz_ms_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ms_login  # noqa: E402


class FalsoNavegador:
    """Recorre fases: correo -> clave -> numero -> mantener -> destino."""
    def __init__(self, fases):
        self.fases, self.i, self.escrito, self.clics = fases, 0, [], 0
        self.current_url = "https://login.microsoftonline.com/x"

    def execute_script(self, js, *args):
        if js is ms_login.JS_FASE:
            f = self.fases[min(self.i, len(self.fases) - 1)]
            self.i += 1
            if f == "destino":
                self.current_url = "https://claromovilco.sharepoint.com/sites/x"
            return {"fase": f, "numero": "47"} if f == "numero" else {"fase": f}
        if js is ms_login.JS_ESCRIBIR:
            self.escrito.append(args)
        else:
            self.clics += 1
        return True


class PruebasLogin(unittest.TestCase):
    def setUp(self):
        self.mostrados = []
        ms_login.mostrar_numero = lambda n: self.mostrados.append(n)
        ms_login.ocultar_numero = lambda: None

    def test_flujo_completo(self):
        d = FalsoNavegador(["correo", "clave", "numero", "numero", "mantener", "destino"])
        ok = ms_login.asegurar_sesion(d, lambda u: "sharepoint.com" in u, "a@b.com", "clave1",
                                      espera_max=5, log=lambda m: None, pausa=0)
        self.assertTrue(ok)
        self.assertEqual([a[1] for a in d.escrito], ["a@b.com", "clave1"])
        self.assertEqual(self.mostrados, ["47"])          # el numero se muestra una sola vez

    def test_sin_clave_no_la_escribe(self):
        d = FalsoNavegador(["correo", "clave", "clave", "destino"])
        ms_login.asegurar_sesion(d, lambda u: "sharepoint.com" in u, "a@b.com", "", espera_max=5,
                                 log=lambda m: None, pausa=0)
        self.assertEqual([a[1] for a in d.escrito], ["a@b.com"])

    def test_tiempo_agotado(self):
        d = FalsoNavegador(["espera"])
        self.assertFalse(ms_login.asegurar_sesion(d, lambda u: False, espera_max=0.05, log=lambda m: None, pausa=0.01))

    def test_ya_en_sharepoint_no_espera(self):
        """Regresion: con la sesion ya abierta debe volver al instante (sin tocar la pagina)."""
        import sp_lector
        d = FalsoNavegador(["destino"])
        d.current_url = "https://claromovilco.sharepoint.com/sites/x"
        self.assertTrue(ms_login.asegurar_sesion(d, sp_lector.url_es_sharepoint, espera_max=2, pausa=0))
        self.assertEqual(d.i, 0)


if __name__ == "__main__":
    unittest.main()
