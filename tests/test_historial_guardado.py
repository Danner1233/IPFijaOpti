# -*- coding: utf-8 -*-
"""Historial: estado Guardada / Sin guardar de la plantilla de cada solicitud."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import plantilla  # noqa: E402
from hac_zac.solicitudes import SolicitudStore, plantilla_guardada  # noqa: E402


class PruebasHistorialGuardado(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="hz_hist_"))
        self.store = SolicitudStore(base / "solicitudes")
        self.txt = base / "64512.txt"

    def test_estados(self):
        self.assertIsNone(plantilla_guardada({}), "sin plantilla no hay nada que guardar")
        self.assertFalse(plantilla_guardada({"preview": "IP 1.1.1.1"}))
        plantilla.guardar("IP 1.1.1.1\n", self.txt)
        self.assertTrue(plantilla_guardada({"preview": "IP 1.1.1.1\n", "archivo": str(self.txt)}))
        self.assertFalse(plantilla_guardada({"preview": "IP 1.1.1.2\n", "archivo": str(self.txt)}), "editada despues")

    def test_listar_trae_el_estado(self):
        plantilla.guardar("IP 1.1.1.1\n", self.txt)
        self.store.guardar({"id": "1", "rr": "1", "preview": "IP 1.1.1.1\n", "archivo": str(self.txt)})
        self.store.guardar({"id": "2", "rr": "2", "preview": "IP 2.2.2.2\n"})
        self.store.guardar({"id": "3", "rr": "3"})
        g = {r["id"]: r["guardada"] for r in self.store.listar()}
        self.assertEqual(g, {"1": True, "2": False, "3": None})

    def test_si_borran_el_txt_queda_sin_guardar(self):
        plantilla.guardar("IP 1.1.1.1\n", self.txt)
        self.store.guardar({"id": "1", "rr": "1", "preview": "IP 1.1.1.1\n", "archivo": str(self.txt)})
        self.txt.unlink()
        self.assertFalse(self.store.listar()[0]["guardada"])


if __name__ == "__main__":
    unittest.main()
