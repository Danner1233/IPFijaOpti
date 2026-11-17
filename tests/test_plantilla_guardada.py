# -*- coding: utf-8 -*-
"""Recordatorio de plantilla sin guardar antes de iniciar otra solicitud."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_plg_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import plantilla  # noqa: E402
import hac_zac_gui as gui  # noqa: E402


class PruebasEstaGuardada(unittest.TestCase):
    def setUp(self):
        self.ruta = Path(tempfile.mkdtemp()) / "64512.txt"

    def test_sin_archivo_no_esta_guardada(self):
        self.assertFalse(plantilla.esta_guardada("IP: 1.2.3.4\n", ""))
        self.assertFalse(plantilla.esta_guardada("IP: 1.2.3.4\n", str(self.ruta)))

    def test_igual_esta_guardada_aunque_cambien_saltos_y_espacios(self):
        self.ruta.write_text("IP: 1.2.3.4  \r\nGW: 1.2.3.1\r\n", encoding="utf-8")
        self.assertTrue(plantilla.esta_guardada("IP: 1.2.3.4\nGW: 1.2.3.1\n", str(self.ruta)))

    def test_editada_despues_de_guardar_no_esta_guardada(self):
        self.ruta.write_text("IP: 1.2.3.4\n", encoding="utf-8")
        self.assertFalse(plantilla.esta_guardada("IP: 1.2.3.9\n", str(self.ruta)))

    def test_con_caso_agregado_al_final_sigue_guardada(self):
        plantilla.guardar("IP: 1.2.3.4\n", self.ruta)
        plantilla.agregar_caso(self.ruta, "TCO-123", "bridge x")
        self.assertTrue(plantilla.esta_guardada("IP: 1.2.3.4\n", str(self.ruta)))

    def test_plantilla_vacia_no_pide_nada(self):
        self.assertTrue(plantilla.esta_guardada("  \n", ""))


def falsa_app(sin_guardar=True, guardar_ok=True):
    guardados = []
    v = types.SimpleNamespace(rec={"key": "k1", "id": "64512"}, sin_guardar=lambda: sin_guardar,
                              _texto=lambda: "IP: 1.2.3.4\n",
                              _guardar=lambda: guardados.append(1) or guardar_ok)
    app = types.SimpleNamespace(v_res=v)
    app.preguntar = lambda **kw: gui.App._plantilla_guardada_o_preguntar(app, **kw)
    return app, guardados


class PruebasRecordatorio(unittest.TestCase):
    def test_guardada_no_pregunta(self):
        app, g = falsa_app(sin_guardar=False)
        with mock.patch.object(gui.messagebox, "askyesnocancel") as p:
            self.assertTrue(app.preguntar())
        p.assert_not_called()

    def test_si_guarda_y_sigue(self):
        app, g = falsa_app()
        with mock.patch.object(gui.messagebox, "askyesnocancel", return_value=True):
            self.assertTrue(app.preguntar())
        self.assertEqual(g, [1])

    def test_no_sigue_sin_guardar_y_no_vuelve_a_preguntar(self):
        app, g = falsa_app()
        with mock.patch.object(gui.messagebox, "askyesnocancel", return_value=False) as p:
            self.assertTrue(app.preguntar())
            self.assertTrue(app.preguntar())
        self.assertEqual(p.call_count, 1)
        self.assertEqual(g, [])

    def test_cancelar_no_inicia(self):
        app, g = falsa_app()
        with mock.patch.object(gui.messagebox, "askyesnocancel", return_value=None):
            self.assertFalse(app.preguntar())

    def test_si_falla_el_guardado_no_inicia(self):
        app, g = falsa_app(guardar_ok=False)
        with mock.patch.object(gui.messagebox, "askyesnocancel", return_value=True):
            self.assertFalse(app.preguntar())

    def test_caso_automatico_pregunta_sin_cancelar(self):
        app, g = falsa_app()
        with mock.patch.object(gui.messagebox, "askyesno", return_value=True) as p, \
                mock.patch.object(gui.messagebox, "askyesnocancel") as c:
            self.assertTrue(app.preguntar(puede_cancelar=False))
        p.assert_called_once()
        c.assert_not_called()
        self.assertEqual(g, [1])


if __name__ == "__main__":
    unittest.main()
