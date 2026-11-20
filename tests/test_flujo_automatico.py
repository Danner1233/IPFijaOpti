# -*- coding: utf-8 -*-
"""Desde el script el flujo arranca solo (fijo) y detenerlo pide confirmacion (por defecto «No»)."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_fa_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import panel_centro as PC  # noqa: E402


class Serv:
    def __init__(self, vivos=False):
        self.vivos, self.inicios, self.paradas = vivos, 0, 0

    def hay_vivos(self):
        return self.vivos

    def iniciar_todo(self, ver):
        self.inicios += 1
        self.vivos = True
        return True

    def detener_todo(self):
        self.paradas += 1
        self.vivos = False


def cola_falsa(desde_script, al_abrir=False, vivos=False):
    c = types.SimpleNamespace(central=False, desde_script=desde_script, serv=Serv(vivos),
                              al_abrir=types.SimpleNamespace(get=lambda: al_abrir), _pintar_flujo=lambda: None,
                              winfo_toplevel=lambda: None)
    c.iniciar = lambda: PC.PanelCola.iniciar_al_abrir(c)
    c.flujo = lambda: PC.PanelCola._flujo(c)
    return c


class PruebasArranque(unittest.TestCase):
    def test_desde_el_script_arranca_aunque_la_casilla_este_apagada(self):
        c = cola_falsa(desde_script=True, al_abrir=False)
        c.iniciar()
        self.assertEqual(c.serv.inicios, 1)

    def test_centro_de_control_respeta_la_casilla(self):
        c = cola_falsa(desde_script=False, al_abrir=False)
        c.iniciar()
        self.assertEqual(c.serv.inicios, 0)

    def test_no_lo_arranca_dos_veces(self):
        c = cola_falsa(desde_script=True, vivos=True)
        c.iniciar()
        self.assertEqual(c.serv.inicios, 0)


class PruebasDetener(unittest.TestCase):
    def test_pregunta_y_si_dice_no_sigue_encendido(self):
        c = cola_falsa(True, vivos=True)
        with mock.patch.object(PC.messagebox, "askyesno", return_value=False) as p:
            c.flujo()
        self.assertEqual(c.serv.paradas, 0)
        kw = p.call_args.kwargs
        self.assertEqual((kw["icon"], kw["default"]), ("warning", "no"), "por defecto queda en No")
        self.assertIn("NO le llegan solicitudes", p.call_args.args[1])

    def test_si_confirma_lo_detiene(self):
        c = cola_falsa(True, vivos=True)
        with mock.patch.object(PC.messagebox, "askyesno", return_value=True):
            c.flujo()
        self.assertEqual(c.serv.paradas, 1)

    def test_iniciar_no_pregunta(self):
        c = cola_falsa(True, vivos=False)
        c.serv.extra = None
        with mock.patch.object(PC.messagebox, "askyesno") as p:
            c.serv.var_ver = types.SimpleNamespace(get=lambda: False)
            c.flujo()
        p.assert_not_called()
        self.assertEqual(c.serv.inicios, 1)


if __name__ == "__main__":
    unittest.main()
