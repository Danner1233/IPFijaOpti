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

    def test_terminar_la_solicitud_fuera_de_turno_no_cuenta(self):
        # turno A (lun) sale 17:30; sigue con la 65164 y la cierra 17:52: se le deja terminar pero NO es hora extra
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "65164", en(17, 31)))
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "", en(17, 52)))
        HE.cerrar(self.c, "Ana", en(17, 55))
        self.assertEqual(self.filas(), [])

    def test_tramo_viejo_de_terminar_solicitud_se_descarta(self):
        cola._escribir(HE.ARCHIVO, {"tipo": HE.SOLICITUD, "desde": en(17, 30).isoformat(), "caso": "1"})
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "1", en(17, 50)))
        self.assertEqual(self.filas(), [])

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

    def test_voluntaria_vence_con_una_abierta_solo_cuenta_lo_pedido(self):
        HE.iniciar_voluntaria(30, "x", "temprano", en(17, 40))
        self.assertIsNone(HE.seguir(self.c, "Ana", "temprano", "777", en(18, 15)), "la termina, pero ya no cuenta")
        HE.seguir(self.c, "Ana", "temprano", "", en(18, 40))
        self.assertEqual([(r["Tipo"], r["Fin"]) for r in self.filas()], [(HE.VOLUNTARIA, "18:10")])

    def test_resumen_del_dia_y_del_mes(self):
        HE.iniciar_voluntaria(60, "x", "temprano", en(17, 40))
        HE.seguir(self.c, "Ana", "temprano", "", en(18, 45))
        self.assertEqual(round(reportes.resumen_dia(self.c, LUNES)["Ana"]["extra"]), 60)
        self.assertEqual(round(reportes.extra_mes(self.c, LUNES)["Ana"]), 60)
        self.assertEqual((reportes.h_min(60), reportes.h_min(95), reportes.h_min(0)), ("1 h 00 min", "1 h 35 min", "—"))


class PruebasTurnoDelDia(unittest.TestCase):
    def test_una_vez_por_dia_aunque_cierre_la_app(self):
        cola._escribir(R.TURNO_HOY, {})
        self.assertEqual(R.turno_elegido_hoy("Ana", en(9)), "")
        R.guardar_turno_hoy("Ana", "c", en(9))
        self.assertEqual(R.turno_elegido_hoy("ana", en(18)), "C", "queda todo el dia (es un archivo)")
        self.assertEqual(R.turno_elegido_hoy("Ana", en(8, dia=LUNES + timedelta(days=1))), "", "al otro dia pregunta")
        self.assertEqual(R.turno_elegido_hoy("Beto", en(10)), "", "es de otra persona")


class PruebasPausas(unittest.TestCase):
    def test_sin_hora_y_media(self):
        self.assertEqual(presencia.MINUTOS_PAUSA, (15, 30, 60))


class PruebasReportesPorPEM(unittest.TestCase):
    def setUp(self):
        self.c = tempfile.mkdtemp()
        cola._escribir("reportes_pendientes.json", [])

    def test_una_carpeta_por_pem_y_por_mes(self):
        reportes.agregar(self.c, "pausas", "Laura Calderón", en(13), ["Laura Calderón", "16/11/2026", "13:00", "13:30",
                                                                    "30,0", 30, "Almuerzo", reportes.REANUDO])
        ruta = os.path.join(self.c, "reportes", "Laura Calderón", "2026-11", "Pausas.csv")
        self.assertTrue(os.path.isfile(ruta), ruta)
        self.assertEqual(reportes.leer(self.c, "pausas", LUNES)[0]["Razón"], "Almuerzo")

    def test_mueve_los_archivos_de_antes(self):
        base = os.path.join(self.c, "reportes")
        os.makedirs(base)
        with open(os.path.join(base, "pausas_2026-11_Laura Calder_n.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write(";".join(reportes.COLUMNAS["pausas"]) + "\r\n")
            f.write("Laura Calderón;16/11/2026;10:00;10:15;15,0;15;Baño;Reanudó\r\n")
        reportes.agregar(self.c, "pausas", "Laura Calderón", en(13), ["Laura Calderón", "16/11/2026", "13:00", "13:30",
                                                                    "30,0", 30, "Almuerzo", reportes.REANUDO])
        filas = reportes.leer(self.c, "pausas", LUNES)
        self.assertEqual([r["Razón"] for r in filas], ["Almuerzo", "Baño"])
        self.assertEqual(sorted(os.listdir(base)), ["Laura Calderón"], "ya no quedan archivos sueltos")


class PruebasPresenciaReparto(unittest.TestCase):
    def test_fuera_de_turno_con_una_abierta(self):
        clave, txt = presencia.situacion("en_linea", "65164", None, "fuera")
        self.assertEqual(clave, "en_proceso")
        self.assertIn("terminando", txt)
        self.assertNotIn("horas extra", txt, "terminarla no es hora extra")

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
