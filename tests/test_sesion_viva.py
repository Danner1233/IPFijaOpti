# -*- coding: utf-8 -*-
"""La sesion del jump host no se cierra: Enter mientras se espera y reconexion si se cayo (SecureCRT simulado)."""
import ast
import io
import os
import time
import types
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cargar(crt):
    with io.open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    quiero = {"mantener_sesion", "esperar_jump_host", "_linea_actual"}
    nodos = [n for n in arbol.body if (isinstance(n, ast.FunctionDef) and n.name in quiero) or
             (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MANTENER_VIVA_S")]
    esp = {"crt": crt, "time": time}
    exec(compile(ast.Module(body=nodos, type_ignores=[]), "script", "exec"), esp)
    return esp


class Crt:
    def __init__(self, conectada=True, conecta_al=0, falla_connect=False):
        self.enviado, self.conexiones = [], 0
        self.falla = falla_connect
        self.Session = types.SimpleNamespace(Connected=conectada, Path="HENDRIX_DEMIMASTER")
        crt = self

        def connect(*a):
            crt.conexiones += 1
            if crt.falla:
                raise RuntimeError("no conecta")
            crt.Session.Connected = True
        self.Session.Connect = connect

        class Pantalla:
            CurrentRow, Columns = 1, 80

            def Send(self, t):
                crt.enviado.append(t)

            def Get(self, *a):
                return "[user@jump ~]$" if crt.Session.Connected else ""
        self.Screen = Pantalla()

    def Sleep(self, ms):
        pass


class PruebasSesionViva(unittest.TestCase):
    def test_conectada_solo_envia_enter(self):
        c = Crt()
        self.assertEqual(cargar(c)["mantener_sesion"](), "ok")
        self.assertEqual(c.enviado, ["\r"])
        self.assertEqual(c.conexiones, 0)

    def test_caida_se_reconecta_y_avisa(self):
        c = Crt(conectada=False)
        avisos = []
        self.assertEqual(cargar(c)["mantener_sesion"](lambda m, n="info": avisos.append(m)), "reconectada")
        self.assertEqual(c.conexiones, 1)
        self.assertIn("reconectada", avisos[0])

    def test_si_no_puede_reconectar_avisa_y_no_revienta(self):
        c = Crt(conectada=False, falla_connect=True)
        avisos = []
        self.assertEqual(cargar(c)["mantener_sesion"](lambda m, n="info": avisos.append(m)), "sin_conexion")
        self.assertEqual(c.conexiones, 6, "3 intentos (cada uno prueba 2 formas de Connect)")
        self.assertIn("no se pudo reconectar", avisos[0])

    def test_cada_4_minutos(self):
        self.assertEqual(cargar(Crt())["MANTENER_VIVA_S"], 240)


if __name__ == "__main__":
    unittest.main()
