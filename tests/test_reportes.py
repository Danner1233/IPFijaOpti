# -*- coding: utf-8 -*-
"""Reportes en la carpeta del equipo: pausas, conexion y solicitudes (CSV para Excel) y resumen del dia."""
import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_rep_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import cola, presencia, reportes as R  # noqa: E402

T = datetime(2026, 11, 18, 12, 0, 0)


def filas(eq, tipo, nombre="Juan Gutierrez", mes=T):
    with open(R.archivo(eq, tipo, nombre, mes), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


class Base(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": tempfile.mkdtemp(prefix="hz_rep_d_")})
        self.env.start()
        self.eq = tempfile.mkdtemp(prefix="hz_rep_e_")

    def tearDown(self):
        self.env.stop()


class PruebasPausas(Base):
    def test_reanudo_antes(self):
        presencia.poner_pausa(60, "Almuerzo", T, self.eq, "Juan Gutierrez")
        presencia.quitar_pausa(self.eq, "Juan Gutierrez", T + timedelta(minutes=42))
        f = filas(self.eq, "pausas")[0]
        self.assertEqual((f["Inicio"], f["Fin"], f["Minutos reales"], f["Minutos elegidos"], f["Razón"],
                          f["Cómo terminó"]), ("12:00", "12:42", "42,0", "60", "Almuerzo", "Reanudó"))

    def test_se_cumplio_el_tiempo_una_sola_fila(self):
        presencia.poner_pausa(15, "", T, self.eq, "Juan Gutierrez")
        self.assertFalse(presencia.cerrar_pausa_vencida(self.eq, "Juan Gutierrez", T + timedelta(minutes=10)))
        self.assertTrue(presencia.cerrar_pausa_vencida(self.eq, "Juan Gutierrez", T + timedelta(minutes=20)))
        self.assertFalse(presencia.cerrar_pausa_vencida(self.eq, "Juan Gutierrez", T + timedelta(minutes=25)))
        f = filas(self.eq, "pausas")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["Fin"], f[0]["Cómo terminó"]), ("12:15", "Se cumplió el tiempo"))

    def test_sin_carpeta_queda_pendiente_y_luego_se_escribe(self):
        presencia.poner_pausa(30, "Reunión", T)
        presencia.quitar_pausa("", "Juan Gutierrez", T + timedelta(minutes=5))
        self.assertEqual(len(cola._leer("reportes_pendientes.json", [])), 1)
        presencia.poner_pausa(30, "Baño", T + timedelta(minutes=10))
        presencia.quitar_pausa(self.eq, "Juan Gutierrez", T + timedelta(minutes=12))
        self.assertEqual([f["Razón"] for f in filas(self.eq, "pausas")], ["Reunión", "Baño"])
        self.assertEqual(cola._leer("reportes_pendientes.json", []), [])


class PruebasConexion(Base):
    def test_tramos_por_cambio_de_estado(self):
        n = "Juan Gutierrez"
        for m, est in ((0, "en_linea"), (1, "en_linea"), (2, "en_linea"), (3, "ausente"), (4, "ausente"),
                       (5, "pausa"), (6, "en_linea")):
            R.seguir_conexion(self.eq, n, est, T + timedelta(minutes=m))
        R.cerrar_conexion(self.eq, n, T + timedelta(minutes=9))
        self.assertEqual([(f["Estado"], f["Desde"], f["Hasta"], f["Minutos"]) for f in filas(self.eq, "conexion")],
                         [("Activo", "12:00", "12:03", "3,0"), ("Ausente", "12:03", "12:05", "2,0"),
                          ("En pausa", "12:05", "12:06", "1,0"), ("Activo", "12:06", "12:09", "3,0")])

    def test_hueco_cuenta_hasta_la_ultima_vez_visto(self):
        R.seguir_conexion(self.eq, "Ana", "en_linea", T)
        R.seguir_conexion(self.eq, "Ana", "en_linea", T + timedelta(minutes=2))
        R.seguir_conexion(self.eq, "Ana", "en_linea", T + timedelta(minutes=40))     # PC dormido 38 min
        f = filas(self.eq, "conexion", "Ana")
        self.assertEqual([(x["Desde"], x["Hasta"]) for x in f], [("12:00", "12:02")])


class PruebasSolicitudes(Base):
    def rec(self, **k):
        r = {"id": "64950", "rr": "123", "red": "ATP", "creada": "2026-11-18T11:30:00",
             "cerrada_en": "2026-11-18T12:10:00", "resultado": "No exitosa", "causa": "ATP No Responde a PING",
             "observacion": "Se llamó  a NOC", "demora": {"tipo": "observacion", "observacion": "NOC tardó"}}
        r.update(k)
        return r

    def test_cierre_y_correccion(self):
        r = self.rec()
        sol = {"id": "64950", "asignada_en": "2026-11-18T11:40:00", "origen": "admin"}
        self.assertEqual(R.registrar_solicitud(self.eq, "Juan Gutierrez", r, sol), "Cierre")
        self.assertIsNone(R.registrar_solicitud(self.eq, "Juan Gutierrez", r, sol), "sin cambios no repite")
        r["resultado"], r["causa"] = "Escalamiento", "Falla Gestor ACS Friendly"
        self.assertEqual(R.registrar_solicitud(self.eq, "Juan Gutierrez", r, sol), "Corrección")
        f = filas(self.eq, "solicitudes")
        self.assertEqual((f[0]["Asignada"], f[0]["Cerrada"], f[0]["Minutos"], f[0]["Límite"], f[0]["Superó el tiempo"],
                          f[0]["Origen"], f[0]["Justificación demora"], f[0]["Observación"]),
                         ("11:40", "12:10", "30,0", "30", "No", "Asignada por el admin", "NOC tardó", "Se llamó a NOC"))
        self.assertEqual(f[1]["Registro"], "Corrección")

    def test_resumen_del_dia(self):
        R.registrar_solicitud(self.eq, "Juan Gutierrez", self.rec(), {"asignada_en": "2026-11-18T11:30:00"})
        R.registrar_solicitud(self.eq, "Juan Gutierrez", self.rec(id="64951", resultado="Exitosa", red="CLARO",
                                                                    cerrada_en="", documentada_en="2026-11-18T11:50:00"),
                              {"asignada_en": "2026-11-18T11:30:00"})
        R.seguir_conexion(self.eq, "Juan Gutierrez", "en_linea", T)
        R.cerrar_conexion(self.eq, "Juan Gutierrez", T + timedelta(minutes=50))
        presencia.poner_pausa(60, "Almuerzo", T, self.eq, "Juan Gutierrez")
        presencia.quitar_pausa(self.eq, "Juan Gutierrez", T + timedelta(minutes=30))
        x = R.resumen_dia(self.eq, T.date())["Juan Gutierrez"]
        self.assertEqual((x["cerradas"], x["exitosas"], x["no_exitosas"], x["superaron"], x["pausas"]),
                         (2, 1, 1, 2, 1), "ATP 40>30 y Claro 20>15")
        self.assertAlmostEqual(x["promedio"], 30.0)
        self.assertAlmostEqual(x["activo"], 50.0)
        self.assertEqual(R.resumen_dia(self.eq, (T + timedelta(days=1)).date()), {})

    def test_servicio_reporta_al_cerrar_sin_forms(self):
        from hac_zac.servicio import Servicio
        sv = Servicio()
        sv.ajustes.update(carpeta_equipo=self.eq, pem_nombre="Juan Gutierrez")
        sv.store.guardar({"id": "70040", "rr": "1", "creada": "2026-11-18T11:00:00"})
        cola.registrar_mia({"id": "70040", "rr": "1"}, "Juan Gutierrez")
        cola.poner_origen("70040", "auto")
        sv.aplicar_resultado("70040", "Escalamiento", "Falla Gestor ACS Friendly", "")
        sv.cerrar_sin_forms("70040")
        f = filas(self.eq, "solicitudes", mes=datetime.now())
        self.assertEqual((f[0]["Solicitud"], f[0]["Resultado"], f[0]["Origen"]),
                         ("70040", "Escalamiento", "Autoasignada"))


if __name__ == "__main__":
    unittest.main()
