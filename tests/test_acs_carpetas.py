# -*- coding: utf-8 -*-
"""Fallas del ACS (MAC/serial no encontrada, ONT mal aprovisionada) con RR / REGIONAL / ALIADO, y plantillas
guardadas por resultado en la carpeta del PEM."""
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_acs_"))
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
from hac_zac import plantilla as P, reportes  # noqa: E402
from test_fallo_copiar import SOLICITUD  # noqa: E402

DATOS = "RR: 64767642\nREGIONAL: Occidente\nALIADO: CONECTAR"


def funciones_script():
    """Las funciones del script de SecureCRT (py2.7/py3) sin cargar todo el script."""
    with open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
        src = f.read()
    ns = {"re": re}
    i = src.index("def solo_ascii")
    j = src.index("\n\n\n", src.index("return t.encode"))
    exec(src[i:j], ns)
    k = src.index("# Fallas del aplicativo ACS")
    exec(src[k:src.index("def consultar_portal")], ns)
    return ns


class PruebasScript(unittest.TestCase):
    def setUp(self):
        self.s = funciones_script()

    def test_no_encontrada(self):
        self.assertEqual(self.s["falla_acs"](self.s["ACS_NO_ENCONTRADA"], SOLICITUD),
                         "NO SE PUDO SACAR DATOS DEL CLIENTE MAC O SERIAL NO ENCONTRADA\n\n" + DATOS)

    def test_mal_aprovisionada(self):
        self.assertEqual(self.s["falla_acs"](self.s["ACS_MAL_APROVISIONADA"], SOLICITUD),
                         "ONT MAL APROVISIONADA, no se cuenta con los datos al cliente\n\n" + DATOS)

    def test_mismos_textos_que_la_ventana(self):
        self.assertEqual((self.s["ACS_NO_ENCONTRADA"], self.s["ACS_MAL_APROVISIONADA"]),
                         (P.ACS_NO_ENCONTRADA, P.ACS_MAL_APROVISIONADA))
        self.assertEqual(self.s["datos_reporte_sol"](SOLICITUD), P.datos_reporte(SOLICITUD))

    def test_el_script_usa_los_mensajes(self):
        with open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("except PortalNoEncontrado:\n        raise ProcesoError(falla_acs(ACS_NO_ENCONTRADA", src)
        self.assertIn("raise ProcesoError(falla_acs(ACS_MAL_APROVISIONADA, txt_sol))", src)
        with open(os.path.join(RAIZ, "portal_csr.py"), encoding="utf-8") as f:
            self.assertIn('codigo="no_encontrado"', f.read())


class PruebasVentana(unittest.TestCase):
    def test_copiar_con_motivo(self):
        err = P.ACS_NO_ENCONTRADA + "\n\n" + DATOS
        self.assertEqual(P.motivo_acs(err), P.ACS_NO_ENCONTRADA)
        self.assertEqual(P.reporte_falla(SOLICITUD, err), P.ACS_NO_ENCONTRADA + "\n\n" + DATOS)
        self.assertEqual(P.reporte_falla(SOLICITUD, P.ACS_MAL_APROVISIONADA),
                         P.ACS_MAL_APROVISIONADA + "\n\n" + DATOS)

    def test_otra_falla_solo_los_datos(self):
        self.assertEqual(P.motivo_acs("No se pudo identificar la IP del Capa 3"), "")
        self.assertEqual(P.reporte_falla(SOLICITUD, "No se pudo identificar la IP del Capa 3"), DATOS)


class PruebasCarpetasPorResultado(unittest.TestCase):
    def setUp(self):
        self.c = tempfile.mkdtemp()
        self.rec = {"id": "65164", "rr": "2637758", "resultado": "Exitosa", "preview": "PLANTILLA\nIP: 1.2.3.4\n",
                    "documentada_en": "2026-11-20T10:00:00"}

    def test_una_sola_carpeta(self):
        r = reportes.guardar_plantilla(self.c, "Danner Arias", self.rec)
        self.assertEqual(r, self.dia("65164_2637758 - Exitosa - Danner Arias.txt"))
        self.assertEqual(os.listdir(os.path.join(self.c, "reportes")), ["SOLICITUDES"],
                         "ya no se crean carpetas por PEM con Exitosas / No exitosas / Escalamiento")

    def test_no_exitosa_y_escalamiento(self):
        for est in ("No exitosa", "Escalamiento"):
            rec = dict(self.rec, id="1" + est[0], resultado=est, documentada_en="", cerrada_en="2026-11-20T11:00:00")
            r = reportes.guardar_plantilla(self.c, "Danner Arias", rec)
            self.assertEqual(os.path.dirname(r), self.dia())
            self.assertIn(" - %s - " % est, r)

    def test_mueve_las_carpetas_por_pem_de_antes(self):
        viejo = os.path.join(self.c, "reportes", "Danner Arias", "Exitosas", "2026-11")
        os.makedirs(viejo)
        with open(os.path.join(viejo, "65000_1.txt"), "w", encoding="utf-8") as f:
            f.write("X")
        t = datetime(2026, 11, 20, 9, 0).timestamp()
        os.utime(os.path.join(viejo, "65000_1.txt"), (t, t))
        reportes.guardar_plantilla(self.c, "Danner Arias", self.rec)
        self.assertEqual(sorted(os.listdir(self.dia())), ["65000_1 - Exitosa - Danner Arias.txt",
                                                          "65164_2637758 - Exitosa - Danner Arias.txt"])
        self.assertFalse(os.path.exists(os.path.join(self.c, "reportes", "Danner Arias", "Exitosas")),
                         "la carpeta vieja se quita")

    def test_sin_resultado_o_sin_carpeta_no_guarda(self):
        self.assertIsNone(reportes.guardar_plantilla(self.c, "Danner Arias", dict(self.rec, resultado="")))
        self.assertIsNone(reportes.guardar_plantilla("", "Danner Arias", self.rec))

    def dia(self, *f):
        return os.path.join(self.c, "reportes", "SOLICITUDES", "11 Noviembre 2026", "20", *f)

    def test_solicitudes_por_mes_y_dia(self):
        reportes.guardar_plantilla(self.c, "Danner Arias", self.rec)
        self.assertEqual(os.listdir(self.dia()), ["65164_2637758 - Exitosa - Danner Arias.txt"])
        with open(self.dia("65164_2637758 - Exitosa - Danner Arias.txt"), encoding="utf-8-sig") as f:
            self.assertEqual(f.read(), "PLANTILLA\nIP: 1.2.3.4\n")

    def test_diciembre_crea_su_carpeta(self):
        reportes.guardar_plantilla(self.c, "Danner Arias", dict(self.rec, documentada_en="2026-12-01T08:30:00"))
        self.assertTrue(os.path.isfile(os.path.join(self.c, "reportes", "SOLICITUDES", "12 Diciembre 2026", "01",
                                                    "65164_2637758 - Exitosa - Danner Arias.txt")))

    def test_cambio_de_resultado_en_el_dia(self):
        reportes.guardar_plantilla(self.c, "Danner Arias", self.rec)
        reportes.guardar_plantilla(self.c, "Danner Arias", dict(self.rec, resultado="Escalamiento"))
        self.assertEqual(os.listdir(self.dia()), ["65164_2637758 - Escalamiento - Danner Arias.txt"])

    def test_varios_pem_el_mismo_dia(self):
        reportes.guardar_plantilla(self.c, "Danner Arias", self.rec)
        reportes.guardar_plantilla(self.c, "Juan Gutierrez", dict(self.rec, id="65170", rr="111"))
        self.assertEqual(sorted(os.listdir(self.dia())), ["65164_2637758 - Exitosa - Danner Arias.txt",
                                                          "65170_111 - Exitosa - Juan Gutierrez.txt"])

    def test_ordenar_las_que_ya_habia(self):
        viejo = os.path.join(self.c, "reportes", "Juan Gutierrez", "No exitosas", "2026-11")
        os.makedirs(viejo)
        ruta = os.path.join(viejo, "65001_9.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("X")
        t = datetime(2026, 11, 19, 15, 0).timestamp()
        os.utime(ruta, (t, t))
        self.assertEqual(reportes.ordenar_existentes(self.c), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.c, "reportes", "SOLICITUDES", "11 Noviembre 2026", "19",
                                                    "65001_9 - No exitosa - Juan Gutierrez.txt")))
        self.assertEqual(reportes.ordenar_existentes(self.c), 0, "no repite")

    def test_no_confunde_los_reportes(self):
        reportes.guardar_plantilla(self.c, "Danner Arias", self.rec)
        self.assertEqual(reportes.leer(self.c, "solicitudes", datetime(2026, 11, 20)), [])


if __name__ == "__main__":
    unittest.main()
