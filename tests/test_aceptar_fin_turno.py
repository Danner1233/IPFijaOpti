# -*- coding: utf-8 -*-
"""Ultimos 5 min del turno: cada solicitud que llega pregunta si se acepta; si no, se devuelve a SharePoint."""
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime

os.environ["HAC_ZAC_DATOS"] = tempfile.mkdtemp(prefix="hz_ac_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import cola, panel_centro as PC  # noqa: E402

LUNES = datetime(2026, 11, 16)


def poner(id_, recibida, estado="asignada"):
    c = cola._cola()
    c["solicitudes"] = [s for s in c["solicitudes"] if s["id"] != id_]
    c["solicitudes"].append({"id": id_, "estado": estado, "asignado": "Ana", "recibida": recibida.isoformat(),
                             "datos": {}, "plantilla": "X"})
    cola._escribir("cola.json", c)


class PruebasPorAceptar(unittest.TestCase):
    def setUp(self):
        cola._escribir("cola.json", {"solicitudes": []})
        cola._escribir(cola.LIBERAR, {})

    def test_solo_las_que_llegan_al_final(self):
        poner("1", LUNES.replace(hour=16))               # turno A sale 17:30
        poner("2", LUNES.replace(hour=17, minute=26))
        self.assertEqual([s["id"] for s in cola.por_aceptar("Ana", "temprano", LUNES.replace(hour=17, minute=27))],
                         ["2"])

    def test_aceptada_no_vuelve_a_preguntar(self):
        poner("2", LUNES.replace(hour=17, minute=26))
        cola.marcar_aceptada("2")
        self.assertEqual(cola.por_aceptar("Ana", "temprano", LUNES.replace(hour=17, minute=27)), [])

    def test_no_la_devuelve_a_sharepoint(self):
        poner("2", LUNES.replace(hour=17, minute=26))
        cola.pedir_liberar("2", "Ana")
        self.assertIn("2", cola.liberar_pendientes())
        self.assertEqual(cola.por_aceptar("Ana", "temprano", LUNES.replace(hour=17, minute=27)), [])

    def test_procesar_solo_no_arranca_la_que_no_acepto(self):
        poner("2", LUNES.replace(hour=17, minute=26))
        procesadas = []
        p = types.SimpleNamespace(auto_proc=types.SimpleNamespace(get=lambda: True), ocupado=lambda: False,
                                  procesar=procesadas.append,
                                  _por_aceptar=lambda: cola.por_aceptar("Ana", "temprano",
                                                                        LUNES.replace(hour=17, minute=27)))
        PC.PanelCola._auto_procesar(p)
        self.assertEqual(procesadas, [])
        cola.marcar_aceptada("2")
        PC.PanelCola._auto_procesar(p)
        self.assertEqual([s["id"] for s in procesadas], ["2"])


if __name__ == "__main__":
    unittest.main()
