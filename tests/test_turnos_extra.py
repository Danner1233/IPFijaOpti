# -*- coding: utf-8 -*-
"""Turno elegido por lista al abrir, fin de turno con una abierta (la termina), horas extra y barra de tareas."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_te_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import cola, horas_extra as HE, presencia, reparto_equipo as R, reportes, turnos as T  # noqa: E402
import navegador  # noqa: E402

LUNES = datetime(2026, 11, 16)          # lunes


def en(h, m=0, dia=LUNES):
    return dia.replace(hour=h, minute=m)


class PruebasListaTurnos(unittest.TestCase):
    def test_opciones_como_el_equipo(self):
        self.assertEqual(T.opcion("A"), "TURNO A   (8:00 AM - 5:30 PM)   LUNES - JUEVES")
        self.assertEqual(T.opcion("D"), "TURNO D   (10:00 AM - 7:00 PM)   VIERNES")
        self.assertEqual([l for l, _ in T.lista_turnos()], list("ABCDEF"))

    def test_letra_a_franja(self):
        self.assertEqual([T.franja_de_letra(l) for l in "abCDEF"],
                         ["temprano", "temprano", "medio", "medio", "tarde", "tarde"])
        self.assertEqual(T.franja_de_letra("Z"), "")

    def test_domingo_no_pregunta(self):
        self.assertFalse(T.hay_turno(LUNES + timedelta(days=6)))
        self.assertTrue(T.hay_turno(LUNES + timedelta(days=5)))


class PruebasEquipo(unittest.TestCase):
    def setUp(self):
        self.c = tempfile.mkdtemp()
        R.guardar_roster(self.c, [{"nombre": "Danner Arias", "activo": True, "franja": ""},
                                  {"nombre": "Nuevo Admin", "activo": False, "franja": ""}])

    def test_lista_del_equipo_mas_los_del_admin(self):
        n = R.nombres_equipo(self.c)
        self.assertEqual(n[:8], list(R.EQUIPO))
        self.assertIn("Nuevo Admin", n)
        self.assertEqual(sum(1 for x in n if x == "Danner Arias"), 1)

    def test_elegir_turno_guarda_la_franja(self):
        self.assertEqual(R.poner_mi_turno(self.c, "danner arias", "E"), "tarde")
        p = next(x for x in R.roster(self.c) if x["nombre"] == "Danner Arias")
        self.assertEqual((p["franja"], p["activo"]), ("tarde", True), "no cambia lo que decide el admin")

    def test_si_no_estaba_lo_agrega_inactivo(self):
        R.poner_mi_turno(self.c, "Laura Calderón", "B")
        p = next(x for x in R.roster(self.c) if x["nombre"] == "Laura Calderón")
        self.assertEqual((p["franja"], p["activo"]), ("temprano", False))


class PruebasRitmo(unittest.TestCase):
    def test_un_minuto_y_medio(self):
        self.assertEqual([R.descanso_s(n) for n in (1, 2, 3, 4, 5, 8)], [90, 90, 90, 45, 0, 0])


class PruebasHorasExtra(unittest.TestCase):
    def setUp(self):
        cola._escribir(HE.ARCHIVO, {})
        self.c = tempfile.mkdtemp()

    def filas(self, dia=LUNES):
        return reportes.leer(self.c, "horas_extra", dia)

    def test_en_turno_no_hay_extra(self):
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "65164", en(16)))

    def test_termina_la_solicitud_despues_del_turno(self):
        # turno A (lun) sale 17:30; a las 17:31 sigue con la 65164
        e = HE.seguir(self.c, "Ana", "temprano", "65164", en(17, 31))
        self.assertEqual((e["tipo"], e["desde"][11:16], e["caso"]), (HE.SOLICITUD, "17:30", "65164"))
        self.assertIsNotNone(HE.seguir(self.c, "Ana", "temprano", "65164", en(17, 50)))
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "", en(17, 52)), "cerro la solicitud")
        f = self.filas()
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["Turno"], f[0]["Fin del turno"], f[0]["Inicio"], f[0]["Fin"], f[0]["Minutos"],
                          f[0]["Tipo"], f[0]["Cómo terminó"]),
                         ("A", "17:30", "17:30", "17:52", "22,0", HE.SOLICITUD, "Terminó la solicitud 65164"))

    def test_cerrar_y_abrir_la_app_no_cuenta_doble(self):
        HE.seguir(self.c, "Ana", "temprano", "1", en(17, 40))
        HE.cerrar(self.c, "Ana", en(17, 45))
        e = HE.seguir(self.c, "Ana", "temprano", "1", en(18, 0))
        self.assertEqual(e["desde"][11:16], "17:45")

    def test_voluntaria_recibe_y_vence(self):
        self.assertTrue(HE.puede_iniciar("temprano", en(17, 40)))
        self.assertFalse(HE.puede_iniciar("temprano", en(10)), "en turno no hace falta")
        e = HE.iniciar_voluntaria(60, "Muchas solicitudes en cola", "temprano", en(17, 40))
        self.assertTrue(HE.recibe(e, en(18, 0)))
        self.assertFalse(HE.recibe(e, en(18, 30)), "15 min antes de terminar ya no recibe")
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "", en(18, 41)))
        f = self.filas()
        self.assertEqual((f[0]["Inicio"], f[0]["Fin"], f[0]["Minutos"], f[0]["Tipo"], f[0]["Motivo"],
                          f[0]["Cómo terminó"]),
                         ("17:40", "18:40", "60,0", HE.VOLUNTARIA, "Muchas solicitudes en cola", HE.SE_CUMPLIO))

    def test_voluntaria_vence_con_una_abierta_y_la_termina(self):
        HE.iniciar_voluntaria(30, "x", "temprano", en(17, 40))
        e = HE.seguir(self.c, "Ana", "temprano", "777", en(18, 15))
        self.assertEqual((e["tipo"], e["desde"][11:16]), (HE.SOLICITUD, "18:10"))
        HE.seguir(self.c, "Ana", "temprano", "", en(18, 20))
        self.assertEqual([r["Tipo"] for r in self.filas()], [HE.VOLUNTARIA, HE.SOLICITUD])

    def test_resumen_del_dia_y_del_mes(self):
        HE.seguir(self.c, "Ana", "temprano", "1", en(17, 31))
        HE.seguir(self.c, "Ana", "temprano", "", en(18, 30))
        self.assertEqual(round(reportes.resumen_dia(self.c, LUNES)["Ana"]["extra"]), 60)
        self.assertEqual(round(reportes.extra_mes(self.c, LUNES)["Ana"]), 60)
        self.assertEqual((reportes.h_min(60), reportes.h_min(95), reportes.h_min(0)), ("1 h 00 min", "1 h 35 min", "—"))


class PruebasPresenciaReparto(unittest.TestCase):
    def test_fuera_de_turno_con_una_abierta(self):
        clave, txt = presencia.situacion("en_linea", "65164", None, "fuera")
        self.assertEqual(clave, "en_proceso")
        self.assertIn("horas extra", txt)

    def test_voluntaria_se_ve_y_recibe(self):
        ahora = datetime.now()
        extra = {"tipo": HE.VOLUNTARIA, "desde": ahora.isoformat(), "hasta": (ahora + timedelta(hours=1)).isoformat()}
        self.assertEqual(presencia.situacion("en_linea", "", None, "fuera", extra)[0], "extra")
        roster = [{"nombre": "Ana", "activo": True, "franja": "temprano"}]
        pres = {"ana": "en_linea"}
        noche = en(19)
        self.assertEqual(R.elegibles(roster, pres, set(), noche), [], "fuera de turno no recibe")
        self.assertEqual([p["nombre"] for p in R.elegibles(roster, pres, set(), noche, extra={"ana"})], ["Ana"])

    def test_el_equipo_publica_las_extra(self):
        c = tempfile.mkdtemp()
        ahora = datetime.now()
        extra = {"tipo": HE.VOLUNTARIA, "desde": ahora.isoformat(), "hasta": (ahora + timedelta(hours=1)).isoformat()}
        presencia.publicar(c, "Ana", ahora, False, ahora, extra=extra)
        self.assertEqual(R.extras_por_nombre(c), {"ana"})
        presencia.publicar(c, "Ana", ahora, False, ahora)
        self.assertEqual(R.extras_por_nombre(c), set())


class PruebasBarraDeTareas(unittest.TestCase):
    def test_estilo(self):
        oculto = navegador.estilo_barra(navegador.WS_EX_APPWINDOW | 0x100, False)
        self.assertTrue(oculto & navegador.WS_EX_TOOLWINDOW)
        self.assertFalse(oculto & navegador.WS_EX_APPWINDOW)
        self.assertEqual(oculto & 0x100, 0x100, "no toca los demas estilos")
        visible = navegador.estilo_barra(oculto, True)
        self.assertFalse(visible & navegador.WS_EX_TOOLWINDOW)
        self.assertTrue(visible & navegador.WS_EX_APPWINDOW)

    def test_descendientes(self):
        pares = [(10, 1), (11, 10), (12, 11), (13, 10), (20, 2)]
        self.assertEqual(navegador.descendientes(10, pares), {10, 11, 12, 13})

    def test_procesos_reales(self):
        if os.name != "nt":
            self.skipTest("solo Windows")
        pares = navegador._procesos()
        self.assertIn(os.getpid(), {p for p, _ in pares})


if __name__ == "__main__":
    unittest.main()
