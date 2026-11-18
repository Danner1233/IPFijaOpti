# -*- coding: utf-8 -*-
"""Reparto del admin entre los PEM: activos y en linea, uno a la vez, por turno, sin devolver lo liberado."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_rq_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import reparto_equipo as R  # noqa: E402

AHORA = datetime(2026, 11, 18, 10, 0, 0)


def item(id_, minutos_atras=10, pem="", est="Sin Asignar", obs=""):
    creada = (AHORA - timedelta(minutes=minutos_atras) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ID": id_, "Created": creada, "PEM_ASIGNADO": pem, "Est_Seg": est, "ActivApoyo": "No",
            "Observaciones": obs}


ROSTER = [{"nombre": "Danner Arias", "activo": True, "ultimo": "2026-11-18T09:00:00"},
          {"nombre": "Camilo Vera", "activo": True, "ultimo": "2026-11-18T08:00:00"},
          {"nombre": "Laura Calderón", "activo": False, "ultimo": ""}]
TODOS_EN_LINEA = {R._plano(p["nombre"]): "en_linea" for p in ROSTER}


class PruebasPlan(unittest.TestCase):
    def test_turno_y_la_mas_antigua_primero(self):
        p = R.plan([item(2, 5), item(1, 20)], ROSTER, TODOS_EN_LINEA, AHORA)
        self.assertEqual([(it["ID"], n) for it, n in p], [(1, "Camilo Vera"), (2, "Danner Arias")])

    def test_inactivo_no_recibe(self):
        nombres = [n for _, n in R.plan([item(i) for i in range(5)], ROSTER, TODOS_EN_LINEA, AHORA)]
        self.assertNotIn("Laura Calderón", nombres)

    def test_ausente_o_desconectado_no_recibe(self):
        pres = dict(TODOS_EN_LINEA, **{R._plano("Camilo Vera"): "ausente"})
        self.assertEqual([n for _, n in R.plan([item(1)], ROSTER, pres, AHORA)], ["Danner Arias"])
        self.assertEqual(R.plan([item(1)], ROSTER, {}, AHORA), [], "sin carpeta del equipo nadie esta en linea")

    def test_ocupado_no_recibe(self):
        items = [item(9, pem="Camilo vera", est="Asignada"), item(1)]
        self.assertEqual([n for _, n in R.plan(items, ROSTER, TODOS_EN_LINEA, AHORA)], ["Danner Arias"])

    def test_cerrada_o_vieja_no_bloquea(self):
        items = [item(8, pem="Camilo Vera", est="No Exitosa"), item(9, 60 * 30, pem="Camilo Vera", est="Asignada"),
                 item(1)]
        self.assertEqual(R.plan(items, ROSTER, TODOS_EN_LINEA, AHORA)[0][1], "Camilo Vera")

    def test_no_se_devuelve_a_quien_la_libero(self):
        obs = "nota tecnico<br>[18/11 09:50] PEM Camilo Vera: libero la solicitud"
        self.assertEqual(R.plan([item(1, obs=obs)], ROSTER, TODOS_EN_LINEA, AHORA)[0][1], "Danner Arias")

    def test_una_por_pem(self):
        self.assertEqual(len(R.plan([item(i) for i in range(6)], ROSTER, TODOS_EN_LINEA, AHORA)), 2)


class PruebasRepartoPublicado(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hz_eq_")

    def test_pem_de_la_lista_no_se_autoasigna_mientras_el_admin_reparte(self):
        R.publicar(self.d, ROSTER, "Danner Arias", AHORA)
        self.assertTrue(R.lo_reparte_el_admin(self.d, "camilo vera", AHORA))
        self.assertTrue(R.lo_reparte_el_admin(self.d, "Laura Calderon", AHORA), "inactivo tampoco se autoasigna")
        self.assertFalse(R.lo_reparte_el_admin(self.d, "Otro PEM", AHORA), "quien no esta en la lista sigue igual")

    def test_si_el_admin_se_detiene_vuelven_a_autoasignarse(self):
        R.publicar(self.d, ROSTER, "Danner Arias", AHORA)
        self.assertFalse(R.lo_reparte_el_admin(self.d, "Camilo Vera", AHORA + timedelta(minutes=R.VIGENTE_MIN + 1)))

    def test_sin_carpeta_o_sin_archivo(self):
        self.assertFalse(R.lo_reparte_el_admin("", "Camilo Vera"))
        self.assertFalse(R.lo_reparte_el_admin(self.d, "Camilo Vera"))


class PruebasEstadoPublicacion(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hz_ep_")

    def test_sin_archivo(self):
        self.assertEqual(R.estado_publicacion(self.d, ROSTER, AHORA)[0], "sin_archivo")
        self.assertEqual(R.estado_publicacion("", ROSTER, AHORA)[0], "sin_archivo")

    def test_al_dia(self):
        R.publicar(self.d, ROSTER, "Danner Arias", AHORA)
        self.assertEqual(R.estado_publicacion(self.d, ROSTER, AHORA + timedelta(minutes=2)), ("ok", 2, []))

    def test_detenido_y_recien_agregado(self):
        R.publicar(self.d, ROSTER[:1], "Danner Arias", AHORA)
        cod, minutos, faltan = R.estado_publicacion(self.d, ROSTER, AHORA + timedelta(minutes=86))
        self.assertEqual((cod, minutos), ("detenido", 86))
        self.assertEqual(faltan, ["Camilo Vera", "Laura Calderón"])


class PruebasPin(unittest.TestCase):
    def test_pin(self):
        g = R.hash_pin("4321")
        self.assertTrue(R.pin_valido("4321", g))
        self.assertFalse(R.pin_valido("1234", g))
        self.assertFalse(R.pin_valido("4321", ""))
        self.assertNotIn("4321", g)


if __name__ == "__main__":
    unittest.main()
