# -*- coding: utf-8 -*-
"""Reparto central: disponibilidad, uno a la vez, turno y cierre al documentar."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_rep_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import reparto as R  # noqa: E402

T0 = datetime(2026, 11, 17, 8, 0, 0)


def item(id_, creada="2026-11-17T12:00:00Z", pem="", est=""):
    return {"ID": id_, "Created": creada, "PEM_ASIGNADO": pem, "Est_Seg": est, "field_1": "6419271%d" % id_,
            "field_2": "Cliente %d" % id_, "ActivApoyo": ""}


def equipo(*nombres, conectados=True, disponibles=True):
    e = R.nuevo_estado()
    for n in nombres:
        R.agregar_pem(e, n)
        if conectados:
            R.latido(e, n, disponibles, {}, T0)
    return e


class PruebasReparto(unittest.TestCase):
    def test_reparte_una_a_cada_disponible_la_mas_antigua_primero(self):
        e = equipo("Ana Uno", "Beto Dos")
        items = [item(3, "2026-11-17T12:03:00Z"), item(1, "2026-11-17T12:01:00Z"), item(2, "2026-11-17T12:02:00Z")]
        p = R.plan(e, items, T0)
        self.assertEqual([str(it["ID"]) for it, _ in p], ["1", "2"])
        self.assertEqual(sorted(n for _, n in p), ["Ana Uno", "Beto Dos"])

    def test_no_disponible_o_desconectado_no_recibe(self):
        e = equipo("Ana Uno", "Beto Dos")
        R.latido(e, "Ana Uno", False, {}, T0)
        self.assertEqual([n for _, n in R.plan(e, [item(1)], T0)], ["Beto Dos"])
        tarde = T0 + timedelta(seconds=R.LATIDO_MAX_S + 5)
        self.assertEqual(R.plan(e, [item(1)], tarde), [], "sin latido reciente nadie recibe")

    def test_una_a_la_vez(self):
        e = equipo("Ana Uno")
        R.registrar_asignacion(e, item(1), "Ana Uno", T0)
        self.assertEqual(R.plan(e, [item(2)], T0), [])

    def test_ocupado_si_sharepoint_le_tiene_una_abierta(self):
        e = equipo("Ana Uno", "Beto Dos")
        items = [item(9, pem="Ana Uno", est="Asignada"), item(10)]
        self.assertEqual([n for _, n in R.plan(e, items, T0)], ["Beto Dos"])

    def test_turno_el_que_lleva_mas_tiempo_sin_recibir(self):
        e = equipo("Ana Uno", "Beto Dos")
        e["pems"]["Ana Uno"]["ultimo"] = "2026-11-17T07:00:00"
        e["pems"]["Beto Dos"]["ultimo"] = "2026-11-17T07:30:00"
        self.assertEqual(R.plan(e, [item(1)], T0)[0][1], "Ana Uno")

    def test_no_reasigna_lo_ya_asignado_ni_lo_cerrado(self):
        e = equipo("Ana Uno", "Beto Dos")
        R.registrar_asignacion(e, item(1), "Ana Uno", T0)
        self.assertEqual(R.plan(e, [item(1), item(2, est="Exitosa")], T0), [])

    def test_latido_entrega_sus_casos_y_al_documentar_queda_libre(self):
        e = equipo("Ana Uno")
        R.registrar_asignacion(e, item(1), "Ana Uno", T0)
        casos, pedir = R.latido(e, "Ana Uno", True, {}, T0)
        self.assertEqual([c["id"] for c in casos], ["1"])
        self.assertEqual(casos[0]["pem"], "Ana Uno")
        casos, pedir = R.latido(e, "Ana Uno", True, {"1": "Exitosa"}, T0)
        self.assertEqual(casos, [])
        self.assertEqual(pedir, {"1": "Exitosa"})
        # SharePoint todavia dice Asignada (el central aun no escribe): igual ya puede recibir otra
        self.assertEqual(R.plan(e, [item(1, pem="Ana Uno", est="Asignada"), item(2)], T0)[0][1], "Ana Uno")

    def test_no_puede_cerrar_casos_de_otro(self):
        e = equipo("Ana Uno", "Beto Dos")
        R.registrar_asignacion(e, item(1), "Ana Uno", T0)
        _, pedir = R.latido(e, "Beto Dos", True, {"1": "Exitosa"}, T0)
        self.assertEqual(pedir, {})
        self.assertEqual(R.abiertas_de(e, "Ana Uno"), ["1"])

    def test_cierre_hecho_a_mano_en_sharepoint(self):
        e = equipo("Ana Uno")
        R.registrar_asignacion(e, item(1), "Ana Uno", T0)
        R.cerrar_por_sp(e, [item(1, pem="Ana Uno", est="Escalamiento")], T0)
        self.assertEqual(R.abiertas_de(e, "Ana Uno"), [])

    def test_tokens(self):
        e = R.nuevo_estado()
        t = R.agregar_pem(e, "  Ana   Uno ")
        self.assertEqual(R.agregar_pem(e, "ana uno"), t, "mismo PEM no se duplica")
        self.assertEqual(R.autenticar(e, t), "Ana Uno")
        self.assertIsNone(R.autenticar(e, "otro"))
        self.assertIsNone(R.autenticar(e, ""))
        t2 = R.nuevo_token(e, "Ana Uno")
        self.assertIsNone(R.autenticar(e, t))
        self.assertEqual(R.autenticar(e, t2), "Ana Uno")


if __name__ == "__main__":
    unittest.main()
