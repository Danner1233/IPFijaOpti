# -*- coding: utf-8 -*-
"""Turnos rotativos, admin de respaldo, respaldo de los PEM, lista compartida y reasignar."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_tu_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sp_lector  # noqa: E402
from hac_zac import cola, presencia, reparto_equipo as R, turnos as T  # noqa: E402

LUNES = datetime(2026, 11, 16)
VIERNES = datetime(2026, 11, 20)
SABADO = datetime(2026, 11, 21)
DOMINGO = datetime(2026, 11, 22)


def a(dia, hh, mm=0):
    return dia.replace(hour=hh, minute=mm)


class PruebasHorarios(unittest.TestCase):
    def test_turno_de_cada_dia(self):
        self.assertEqual([T.turno_del_dia(f, LUNES) for f in ("temprano", "medio", "tarde")], ["A", "C", "E"])
        self.assertEqual([T.turno_del_dia(f, VIERNES) for f in ("temprano", "medio", "tarde")], ["B", "D", "F"])
        self.assertEqual([T.turno_del_dia(f, SABADO) for f in ("temprano", "medio", "tarde")], ["B", "D", "F"],
                         "el sabado usa los turnos del viernes")
        self.assertIsNone(T.turno_del_dia("temprano", DOMINGO))
        self.assertIsNone(T.turno_del_dia("", LUNES))

    def test_situacion_y_corte(self):
        self.assertEqual(T.situacion("temprano", a(LUNES, 7, 59)), "antes")
        self.assertEqual(T.situacion("temprano", a(LUNES, 8, 0)), "en_turno")
        self.assertEqual(T.situacion("temprano", a(LUNES, 16, 59)), "en_turno")
        self.assertEqual(T.situacion("temprano", a(LUNES, 17, 0)), "corte", "30 min antes de las 17:30")
        self.assertEqual(T.situacion("temprano", a(LUNES, 17, 30)), "fuera")
        self.assertEqual(T.situacion("tarde", a(VIERNES, 19, 29)), "en_turno")
        self.assertEqual(T.situacion("tarde", a(VIERNES, 19, 30)), "corte")
        self.assertEqual(T.situacion("medio", a(DOMINGO, 12)), "fuera")
        self.assertEqual(T.situacion("", a(DOMINGO, 3)), "sin_franja", "sin franja no hay restriccion")
        self.assertTrue(T.puede_recibir("", a(DOMINGO, 3)))
        self.assertFalse(T.puede_recibir("tarde", a(LUNES, 9)))

    def test_aviso_y_texto(self):
        self.assertTrue(T.aviso_salida("medio", a(LUNES, 18, 52)))
        self.assertFalse(T.aviso_salida("medio", a(LUNES, 18, 40)))
        self.assertEqual(T.texto("medio", LUNES), "Turno C 9:30–19:00")
        self.assertEqual(T.texto("medio", DOMINGO), "Sin turno hoy")


ROSTER = [{"nombre": "Ana", "activo": True, "ultimo": "", "franja": "temprano"},
          {"nombre": "Beto", "activo": True, "ultimo": "", "franja": "tarde"}]


def libre(id_):
    return {"ID": id_, "Created": "2026-11-16T12:00:00Z", "PEM_ASIGNADO": "", "Est_Seg": "Sin Asignar",
            "ActivApoyo": "No", "Observaciones": ""}


class PruebasPlanConTurnos(unittest.TestCase):
    def test_solo_recibe_quien_esta_en_turno(self):
        pres = {"ana": "en_linea", "beto": "en_linea"}
        self.assertEqual([n for _, n in R.plan([libre(1), libre(2)], ROSTER, pres, a(LUNES, 9))], ["Ana"])
        self.assertEqual([n for _, n in R.plan([libre(1), libre(2)], ROSTER, pres, a(LUNES, 17, 10))], ["Beto"],
                         "Ana ya esta en su corte de 30 min")
        self.assertEqual(R.plan([libre(1)], ROSTER, pres, a(LUNES, 19, 45)), [], "Beto en corte; Ana ya salio")


class Base(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_tu_d_")})
        self.env.start()
        self.eq = tempfile.mkdtemp(prefix="hz_tu_e_")

    def tearDown(self):
        self.env.stop()


class PruebasRosterCompartido(Base):
    def test_se_crea_con_la_lista_local_y_se_comparte(self):
        cola.agregar_ingeniero("Ana")
        self.assertEqual([p["nombre"] for p in R.roster(self.eq)], ["Ana"])
        self.assertTrue(os.path.exists(R.ruta_roster(self.eq)))
        R.agregar(self.eq, "Beto")
        R.poner_activo(self.eq, "Beto", True)
        R.poner_franja(self.eq, "Beto", "Tarde")
        with open(R.ruta_roster(self.eq), encoding="utf-8") as f:
            b = [p for p in json.load(f)["pems"] if p["nombre"] == "Beto"][0]
        self.assertEqual((b["activo"], b["franja"]), (True, "tarde"))
        self.assertEqual(R.franja_de(self.eq, "beto"), "tarde")


class PruebasQuienReparte(Base):
    def test_admin_de_respaldo_toma_el_reparto(self):
        t = datetime.now()
        R.publicar(self.eq, ROSTER, "Danner Arias", t)
        self.assertTrue(R.debo_repartir(self.eq, "Danner Arias", t + timedelta(seconds=10)))
        self.assertFalse(R.debo_repartir(self.eq, "Laura", t + timedelta(seconds=30)), "reparte Danner")
        self.assertTrue(R.debo_repartir(self.eq, "Laura", t + timedelta(seconds=R.LIDER_S + 1)), "Danner se fue")

    def test_respaldo_de_los_pem(self):
        R.guardar_roster(self.eq, ROSTER)
        t = a(LUNES, 9)
        R.publicar(self.eq, ROSTER, "Danner", t)
        self.assertFalse(R.respaldo_activo(self.eq, "Ana", t + timedelta(minutes=2)), "hay admin repartiendo")
        self.assertTrue(R.respaldo_activo(self.eq, "Ana", t + timedelta(minutes=6)))
        self.assertFalse(R.respaldo_activo(self.eq, "Beto", t + timedelta(minutes=6)), "Beto no esta en turno")
        R.publicar(self.eq, ROSTER, "Danner", t, respaldo=False)
        self.assertFalse(R.respaldo_activo(self.eq, "Ana", t + timedelta(minutes=6)), "el admin apago el respaldo")

    def test_sin_archivo_hay_respaldo_si_esta_en_la_lista(self):
        R.guardar_roster(self.eq, ROSTER)
        self.assertTrue(R.respaldo_activo(self.eq, "Ana", a(LUNES, 9)))
        self.assertFalse(R.respaldo_activo(self.eq, "Zoe", a(LUNES, 9)), "quien no esta en la lista, no")


class Driver:
    def __init__(self):
        self.asignaciones, self.reasignaciones = [], []

    def execute_async_script(self, js, *args):
        if js is sp_lector.JS_TOMAR:
            self.asignaciones.append((args[2], args[3]))
        if js is sp_lector.JS_REASIGNAR:
            self.reasignaciones.append(args[2:6])
        return {"ok": True, "antes": "Asignada"}


class PruebasLector(Base):
    def aj(self, yo):
        return {"rol_admin": True, "admin_repartir": True, "admin_simular": False, "carpeta_equipo": self.eq,
                "pem_nombre": yo}

    def test_el_admin_de_respaldo_no_reparte_mientras_otro_lo_hace(self):
        R.guardar_roster(self.eq, [dict(p, franja="") for p in ROSTER])
        for n in ("Ana", "Beto"):
            presencia.publicar(self.eq, n, datetime.now(), False)
        R.publicar(self.eq, ROSTER, "Danner")
        d, avisos = Driver(), []
        self.assertEqual(sp_lector.repartir_equipo(d, [libre(1)], self.aj("Laura"), log=avisos.append), [])
        self.assertIn("respaldo", avisos[0])
        self.assertEqual(len(sp_lector.repartir_equipo(d, [libre(1)], self.aj("Danner"), log=lambda m: None)), 1)

    def test_reasignar_y_soltar(self):
        cola.pedir_reasignar("64950", "Ana", "Beto", "Danner")
        d = Driver()
        self.assertEqual(sp_lector.enviar_reasignaciones(d), 1)
        id_, de, a_, nota = d.reasignaciones[0]
        self.assertEqual((id_, de, a_), ("64950", "Ana", "Beto"))
        self.assertIn("Admin Danner: reasignó la solicitud de Ana a Beto", nota)
        self.assertEqual(cola.reasignar_pendientes(), {})
        cola.registrar_mia({"id": "64950", "rr": "1"}, "Ana")
        it = dict(libre(64950), PEM_ASIGNADO="Beto", Est_Seg="Asignada")
        self.assertEqual(cola.soltar_si_ya_no_es_mia([it], "Ana"), ["64950"])
        self.assertEqual(cola.mis_casos("Ana"), [])
        self.assertEqual(cola.soltar_si_ya_no_es_mia([it], "Ana"), [], "una sola vez")


class PruebasSituacion(unittest.TestCase):
    def test_fuera_de_turno_y_cierre(self):
        self.assertEqual(presencia.situacion("en_linea", "", None, "fuera")[0], "fuera_turno")
        self.assertEqual(presencia.situacion("en_linea", "", None, "corte")[0], "cierre")
        self.assertEqual(presencia.situacion("en_linea", "64950", None, "fuera")[0], "en_proceso",
                         "si trabaja una solicitud se ve En proceso aunque se le paso la hora")
        self.assertIn("64950", presencia.situacion("desconectado", "64950")[1])


if __name__ == "__main__":
    unittest.main()
