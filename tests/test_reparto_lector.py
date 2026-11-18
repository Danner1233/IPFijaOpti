# -*- coding: utf-8 -*-
"""Reparto del admin dentro del Lector de SharePoint (SharePoint simulado)."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_rl_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sp_lector  # noqa: E402
from hac_zac import cola, presencia, reparto_equipo  # noqa: E402


class Driver:
    def __init__(self):
        self.asignaciones = []

    def execute_async_script(self, js, *args):
        if js is sp_lector.JS_TOMAR:
            self.asignaciones.append((args[2], args[3]))
        return {"ok": True, "antes": ""}


def libre(id_, minutos=10):
    c = (datetime.now() - timedelta(minutes=minutos)).astimezone().isoformat(timespec="seconds")
    return {"ID": id_, "Created": c, "PEM_ASIGNADO": "", "Est_Seg": "Sin Asignar", "ActivApoyo": "No",
            "Observaciones": ""}


class PruebasRepartoEnLector(unittest.TestCase):
    def setUp(self):
        self.datos = tempfile.mkdtemp(prefix="hz_rl_d_")
        self.equipo = tempfile.mkdtemp(prefix="hz_rl_e_")
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": self.datos})
        self.env.start()
        for n in ("Danner Arias", "Camilo Vera", "Laura Calderon"):
            cola.agregar_ingeniero(n)
        cola.poner_activo("Danner Arias", True)
        cola.poner_activo("Camilo Vera", True)
        ahora = datetime.now()
        presencia.publicar(self.equipo, "Danner Arias", ahora, False, ahora)
        presencia.publicar(self.equipo, "Camilo Vera", ahora, False, ahora)
        presencia.publicar(self.equipo, "Laura Calderon", ahora, False, ahora)     # en linea pero inactiva
        self.aj = {"rol_admin": True, "admin_repartir": True, "admin_simular": False,
                   "carpeta_equipo": self.equipo, "pem_nombre": "Danner Arias"}

    def tearDown(self):
        self.env.stop()

    def test_reparte_publica_y_actualiza_el_turno(self):
        d = Driver()
        hechas = sp_lector.repartir_equipo(d, [libre(1, 30), libre(2, 20), libre(3, 10)], self.aj, log=lambda m: None)
        self.assertEqual(sorted(n for _, n in hechas), ["Camilo Vera", "Danner Arias"])
        self.assertEqual(len(d.asignaciones), 2, "una por PEM; la 3 espera")
        self.assertNotIn("Laura Calderon", [n for _, n in d.asignaciones])
        self.assertTrue(all(i.get("ultimo") for i in cola.ingenieros() if i["activo"]))
        self.assertTrue(reparto_equipo.lo_reparte_el_admin(self.equipo, "Camilo Vera"), "los PEM ya no se autoasignan")

    def test_simulacion_no_escribe_ni_publica(self):
        d, avisos = Driver(), []
        self.aj["admin_simular"] = True
        self.assertEqual(sp_lector.repartir_equipo(d, [libre(1)], self.aj, log=avisos.append), [])
        self.assertEqual(d.asignaciones, [])
        self.assertIn("simulacion", avisos[0])
        self.assertFalse(reparto_equipo.lo_reparte_el_admin(self.equipo, "Camilo Vera"))

    def test_sin_rol_o_sin_reparto_no_hace_nada(self):
        d = Driver()
        for cambio in ({"rol_admin": False}, {"admin_repartir": False}):
            self.assertEqual(sp_lector.repartir_equipo(d, [libre(1)], dict(self.aj, **cambio)), [])
        self.assertEqual(d.asignaciones, [])

    def test_sin_carpeta_avisa(self):
        avisos = []
        self.assertEqual(sp_lector.repartir_equipo(Driver(), [libre(1)], dict(self.aj, carpeta_equipo=""),
                                                   log=avisos.append), [])
        self.assertIn("carpeta del equipo", avisos[0])


if __name__ == "__main__":
    unittest.main()
