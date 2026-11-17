# -*- coding: utf-8 -*-
"""Lanzador de un clic (SecureCRT /S sesion /SCRIPT) y espera del jump host en el script."""
import ast
import io
import os
import sys
import tempfile
import time
import types
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import iniciar_hac_zac as L  # noqa: E402


class PruebasComando(unittest.TestCase):
    def setUp(self):
        self.exe = os.path.join(tempfile.mkdtemp(), "SecureCRTPortable.exe")
        open(self.exe, "w").close()

    def test_con_sesion(self):
        cmd = L.comando({"securecrt_exe": '"%s"' % self.exe, "sesion_crt": "HENDRIX_DEMIMASTER"})
        self.assertEqual(cmd[:3], [self.exe, "/S", "HENDRIX_DEMIMASTER"])
        self.assertEqual(cmd[3], "/SCRIPT")
        self.assertTrue(cmd[4].endswith("SCRIPT_HAC_ZAC_UNIFICADO.py"))

    def test_sin_sesion_solo_script(self):
        self.assertEqual(L.comando({"securecrt_exe": self.exe})[1], "/SCRIPT")

    def test_errores_claros(self):
        with self.assertRaises(ValueError) as e:
            L.comando({})
        self.assertIn("Ruta de SecureCRT", str(e.exception))
        with self.assertRaises(ValueError) as e:
            L.comando({"securecrt_exe": self.exe + "_no"})
        self.assertIn("No existe", str(e.exception))


def _funciones(*nombres, crt=None):
    with io.open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    nodos = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name in nombres]
    espacio = {"crt": crt, "time": time}
    exec(compile(ast.Module(body=nodos, type_ignores=[]), "script", "exec"), espacio)
    return espacio


class CrtFalso:
    """Sesion que conecta al 3er segundo, pide clave y luego muestra el prompt del jump host."""

    def __init__(self, pantallas):
        self.pantallas, self.i = pantallas, 0
        self.Session = types.SimpleNamespace(Connected=False)
        crt = self

        class Pantalla:
            CurrentRow, Columns = 1, 80

            def Get(self, *a):
                return crt.pantallas[min(crt.i, len(crt.pantallas) - 1)][1]
        self.Screen = Pantalla()

    def Sleep(self, ms):
        self.i += 1
        self.Session.Connected = self.pantallas[min(self.i, len(self.pantallas) - 1)][0]


class PruebasEsperaJumpHost(unittest.TestCase):
    def test_espera_conexion_y_clave_hasta_el_prompt(self):
        crt = CrtFalso([(False, ""), (False, ""), (True, "login as: user"), (True, "user@172.31.238.6's password:"),
                        (True, "[user@jumphost ~]$")])
        f = _funciones("esperar_jump_host", "_linea_actual", crt=crt)
        self.assertTrue(f["esperar_jump_host"](maximo_s=30))
        self.assertEqual(crt.i, 4)

    def test_si_nunca_conecta_devuelve_false(self):
        crt = CrtFalso([(False, "")])
        f = _funciones("esperar_jump_host", "_linea_actual", crt=crt)
        t0 = time.time()
        self.assertFalse(f["esperar_jump_host"](maximo_s=0.2))
        self.assertLess(time.time() - t0, 2)

    def test_ya_conectado_sigue_de_una(self):
        crt = CrtFalso([(True, "jumphost#")])
        crt.Session.Connected = True
        f = _funciones("esperar_jump_host", "_linea_actual", crt=crt)
        self.assertTrue(f["esperar_jump_host"]())
        self.assertEqual(crt.i, 0)


if __name__ == "__main__":
    unittest.main()
