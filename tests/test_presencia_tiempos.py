# -*- coding: utf-8 -*-
"""Presencia del equipo (en linea / ausente / desconectado) y tiempo de gestion con limite por red."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import presencia as P, tiempos as T  # noqa: E402

T0 = datetime(2026, 11, 17, 9, 0, 0)


class PruebasPresencia(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hz_pres_")

    def test_en_linea_ausente_desconectado(self):
        P.publicar(self.d, "Ana Uno", T0, False, T0)                                   # uso ahora
        P.publicar(self.d, "Beto Dos", T0 - timedelta(minutes=6), False, T0)           # 6 min sin uso
        P.publicar(self.d, "Caro Tres", T0 - timedelta(minutes=20), True, T0)          # proceso corriendo
        e = {x["nombre"]: x["estado"] for x in P.equipo(self.d, T0)}
        self.assertEqual(e, {"Ana Uno": "en_linea", "Beto Dos": "ausente", "Caro Tres": "en_linea"})
        tarde = T0 + timedelta(seconds=P.DESCONECTADO_S + 10)
        self.assertTrue(all(x["estado"] == "desconectado" for x in P.equipo(self.d, tarde)))

    def test_orden_en_linea_primero(self):
        P.publicar(self.d, "Zeta", T0, False, T0)
        P.publicar(self.d, "Alfa", T0 - timedelta(minutes=10), False, T0)
        self.assertEqual([x["nombre"] for x in P.equipo(self.d, T0)], ["Zeta", "Alfa"])

    def test_suma_minutos_en_linea_sin_contar_ausencias(self):
        t = T0
        for _ in range(10):                                  # 10 min usando la app (un tick por minuto)
            P.publicar(self.d, "Ana", t, False, t)
            t += timedelta(minutes=1)
        for _ in range(10):                                  # luego 10 min sin tocarla
            P.publicar(self.d, "Ana", T0 + timedelta(minutes=9), False, t)
            t += timedelta(minutes=1)
        m = P.equipo(self.d, t - timedelta(minutes=1))[0]["en_linea_hoy_min"]
        self.assertTrue(13 <= m <= 15, m)                    # 10 de uso + los 5 de gracia antes de "ausente"

    def test_dos_ventanas_en_el_mismo_pc_no_cuentan_doble(self):
        for i in range(5):
            t = T0 + timedelta(minutes=i)
            P.publicar(self.d, "Ana", t, False, t)                       # ventana del script
            P.publicar(self.d, "Ana", None, False, t + timedelta(seconds=1))   # centro de control (sin uso)
        r = P.equipo(self.d, T0 + timedelta(minutes=4, seconds=2))[0]
        self.assertEqual(r["estado"], "en_linea", "la actividad de una ventana vale para el PC")
        self.assertLessEqual(r["en_linea_hoy_min"], 4)

    def test_pc_dormido_no_suma_horas(self):
        P.publicar(self.d, "Ana", T0, False, T0)
        P.publicar(self.d, "Ana", T0 + timedelta(hours=3), False, T0 + timedelta(hours=3))
        self.assertLessEqual(P.equipo(self.d, T0 + timedelta(hours=3))[0]["en_linea_hoy_min"], 2)

    def test_nuevo_dia_empieza_en_cero(self):
        P.publicar(self.d, "Ana", T0, False, T0)
        P.publicar(self.d, "Ana", T0 + timedelta(minutes=30), False, T0 + timedelta(minutes=30))
        manana = T0 + timedelta(days=1)
        P.publicar(self.d, "Ana", manana, False, manana)
        self.assertEqual(P.equipo(self.d, manana)[0]["en_linea_hoy_min"], 0)

    def test_carpeta_inexistente_y_nombres_raros(self):
        self.assertEqual(P.equipo(os.path.join(self.d, "no_existe")), [])
        P.publicar(self.d, "Jhan pool / guerra", T0, False, T0)
        self.assertEqual(P.equipo(self.d, T0)[0]["nombre"], "Jhan pool / guerra")
        with open(P.archivo(self.d, "Jhan pool / guerra"), encoding="utf-8") as f:
            self.assertNotIn("cliente", json.load(f))

    def test_hace(self):
        self.assertEqual(P.hace((T0 - timedelta(minutes=7)).isoformat(), T0), "hace 7 min")
        self.assertEqual(P.hace("", T0), "—")


def sol(red="CLARO"):
    return "++++++SOLICITUD ID: 1++++++\nPROPIEDAD RED: %s\nCUENTA RR: 111\n" % red


class PruebasTiempos(unittest.TestCase):
    def test_limites_por_red(self):
        self.assertEqual(T.red_de({"txt_sol": sol("CLARO")}), "CLARO")
        self.assertEqual(T.red_de({"txt_sol": sol("ONNET")}), "ONNET")
        self.assertEqual(T.red_de({"txt_sol": sol("ATP")}), "ATP")
        self.assertEqual(T.red_de({"red": "ONNET"}), "ONNET", "sin solicitud, por el capa 2")
        self.assertEqual(T.red_de({}), "CLARO")
        self.assertEqual(T.limite_min("CLARO"), 15)
        self.assertEqual(T.limite_min("ONNET"), 30)

    def test_corre_desde_la_asignacion_y_para_al_documentar(self):
        rec = {"txt_sol": sol(), "creada": "2026-11-17T09:10:00"}
        cola = {"asignada_en": "2026-11-17T09:00:00"}
        m = T.medir(rec, cola, T0 + timedelta(minutes=12))
        self.assertEqual((int(m["minutos"]), m["excedido"]), (12, False))
        self.assertTrue(T.medir(rec, cola, T0 + timedelta(minutes=16))["excedido"])
        rec["documentada_en"] = "2026-11-17T09:14:00"
        m = T.medir(rec, cola, T0 + timedelta(hours=2))
        self.assertEqual((int(m["minutos"]), m["excedido"]), (14, False), "despues de documentar no sigue contando")

    def test_sin_cola_usa_la_creacion(self):
        rec = {"txt_sol": sol("ONNET"), "creada": "2026-11-17T09:00:00"}
        m = T.medir(rec, None, T0 + timedelta(minutes=25))
        self.assertEqual((m["limite"], m["excedido"]), (30, False))
        self.assertEqual(T.texto(T.medir(rec, None, T0 + timedelta(minutes=31))), "31/30 min ⚠")

    def test_justificacion_claro_fotos(self):
        self.assertFalse(T.justificacion_valida("CLARO", {"observacion": "larga observacion"})[0])
        self.assertTrue(T.justificacion_valida("CLARO", {"fotos": ["a.jpg"]})[0])
        self.assertFalse(T.justificacion_valida("CLARO", {"fotos": ["%d.jpg" % i for i in range(6)]})[0])
        self.assertTrue(T.justificacion_valida("CLARO", {"tipo": "pem"})[0])

    def test_justificacion_neutra_observacion(self):
        self.assertFalse(T.justificacion_valida("ATP", {"observacion": "corta"})[0])
        self.assertTrue(T.justificacion_valida("ONNET", {"observacion": "El ATP no respondia la validacion"})[0])
        self.assertTrue(T.justificacion_valida("ONNET", {"tipo": "pem"})[0])

    def test_necesita_justificar(self):
        rec = {"txt_sol": sol(), "creada": "2026-11-17T09:00:00"}
        tarde = T0 + timedelta(minutes=20)
        self.assertTrue(T.necesita_justificar(rec, None, tarde))
        rec["demora"] = {"tipo": "pem"}
        self.assertFalse(T.necesita_justificar(rec, None, tarde))
        self.assertFalse(T.necesita_justificar({"txt_sol": sol(), "creada": "2026-11-17T09:00:00"}, None,
                                               T0 + timedelta(minutes=5)))


if __name__ == "__main__":
    unittest.main()
