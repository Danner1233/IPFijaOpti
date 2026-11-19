# -*- coding: utf-8 -*-
"""Solo los administradores asignan, PIN fijo de admin y estados del equipo (En proceso / Disponible / pausa)."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_sa_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import cola, presencia, reparto_equipo  # noqa: E402

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = datetime(2026, 11, 18, 16, 0, 0)


class PruebasSoloAdmin(unittest.TestCase):
    def test_la_app_del_pem_no_se_autoasigna(self):
        self.assertFalse(cola.auto_asignar_configurado())
        with open(os.path.join(AQUI, "sp_lector.py"), encoding="utf-8") as f:
            s = f.read()
        bucle = s[s.index("def main("):]
        self.assertIn("repartir_equipo(", bucle, "el admin sigue repartiendo")
        i = bucle.index("tomar_libre(")
        self.assertIn("respaldo_activo(", bucle[:i], "el PEM solo toma una libre como RESPALDO (sin admin)")

    def test_pin_admin_fijo(self):
        self.assertTrue(reparto_equipo.pin_admin_valido("2416"))
        self.assertTrue(reparto_equipo.pin_admin_valido(" 2416 "))
        self.assertFalse(reparto_equipo.pin_admin_valido("1234"))
        self.assertFalse(reparto_equipo.pin_admin_valido(""))
        self.assertNotIn("2416", reparto_equipo.PIN_ADMIN, "solo la huella en el codigo")


class PruebasEstados(unittest.TestCase):
    def test_situacion(self):
        S = presencia.situacion
        self.assertEqual(S("en_linea", "64950"), ("en_proceso", "● En proceso · 64950"))
        self.assertEqual(S("en_linea", ""), ("disponible", "● Disponible"))
        self.assertEqual(S("ausente", "64950")[0], "ausente")
        self.assertEqual(S("desconectado", "64950")[0], "desconectado")
        self.assertEqual(S("pausa", "", {"razon": "Almuerzo", "hasta": "2026-11-18T13:00:00"}),
                         ("pausa", "⏸ En pausa: Almuerzo (hasta 13:00)"))

    def test_se_publica_la_solicitud_en_proceso(self):
        eq = tempfile.mkdtemp(prefix="hz_sa_e_")
        presencia.publicar(eq, "Juan Gutierrez", T, False, T, caso="64950")
        presencia.publicar(eq, "Laura Calderon", T, False, T)
        f = {x["nombre"]: x for x in presencia.equipo(eq, T + timedelta(minutes=1))}
        self.assertEqual(presencia.situacion(f["Juan Gutierrez"]["estado"], f["Juan Gutierrez"]["caso"])[0],
                         "en_proceso")
        self.assertEqual(presencia.situacion(f["Laura Calderon"]["estado"], f["Laura Calderon"]["caso"])[0],
                         "disponible")


if __name__ == "__main__":
    unittest.main()
