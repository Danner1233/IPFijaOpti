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
    nombres_extra = {"_PIDE_DATOS"}
    nodos = [n for n in arbol.body if (isinstance(n, ast.FunctionDef) and n.name in quiero) or
             (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ({"MANTENER_VIVA_S"} | nombres_extra))]
    esp = {"crt": crt, "time": getattr(crt, "reloj", time)}
    exec(compile(ast.Module(body=nodos, type_ignores=[]), "script", "exec"), esp)
    return esp


class Reloj:
    """time.time() falso: avanza solo cuando el script hace crt.Sleep (las pruebas no esperan de verdad)."""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t


class Crt:
    def __init__(self, conectada=True, conecta_al=0, falla_connect=False):
        self.enviado, self.conexiones = [], 0
        self.reloj = Reloj()
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
        self.reloj.t += ms / 1000.0


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
        self.assertEqual(c.conexiones, 2, "un solo intento (prueba 2 formas de Connect)")
        self.assertIn("desconectada", avisos[0])

    def test_cada_4_minutos(self):
        self.assertEqual(cargar(Crt())["MANTENER_VIVA_S"], 240)


class PruebasSesionLista(unittest.TestCase):
    """La 1a version esperaba un prompt terminado en $ # > ] y con otro prompt se quedaba minutos esperando."""

    def _crt(self, lineas):
        c = Crt()
        seq = iter(lineas)
        estado = {"l": next(seq)}

        class Pantalla:
            CurrentRow, Columns = 1, 80

            def Get(self, *a):
                return estado["l"]

            def Send(self, t):
                pass
        c.Screen = Pantalla()

        def dormir(ms):
            c.reloj.t += ms / 1000.0
            estado["l"] = next(seq, estado["l"])
        c.Sleep = dormir
        return c

    def test_prompt_cualquiera_quieto_es_listo(self):
        c = self._crt(["Last login: Tue Nov 17", "HENDRIX_DEMIMASTER@jump ~ ", "HENDRIX_DEMIMASTER@jump ~ ",
                       "HENDRIX_DEMIMASTER@jump ~ "])
        t0 = time.time()
        self.assertTrue(cargar(c)["esperar_jump_host"](30))
        self.assertLess(time.time() - t0, 2)

    def test_pidiendo_clave_no_es_listo(self):
        c = self._crt(["user@172.31.238.6's password: "])
        self.assertFalse(cargar(c)["esperar_jump_host"](0.3))

    def test_llega_una_solicitud_y_deja_de_esperar(self):
        c = Crt(conectada=False, falla_connect=True)
        t0 = time.time()
        r = cargar(c)["mantener_sesion"](None, abortar=lambda: True)
        self.assertEqual(r, "interrumpida")
        self.assertLess(time.time() - t0, 1)


if __name__ == "__main__":
    unittest.main()
