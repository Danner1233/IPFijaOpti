# -*- coding: utf-8 -*-
"""Al fallar: datos para reportar (RR / REGIONAL / ALIADO) y nombre del cliente como lo pone el script."""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_fc_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import plantilla as P  # noqa: E402

SOLICITUD = """++++++SOLICITUD ID: 65079++++++

TIPO SOLICITUD CONFIG:
PROPIEDAD RED: CLARO

SERVICIO SOBRE ATP:
NAP ATP:
DIRECCIÓN CLIENTE:

NODO: OCDICT

CUENTA RR: 64767642.0000000
OT/LLs RR: 482437473
NOMBRE CLIENTE: AGRICOLA A UTOMOTRIZ SAS
REGIONAL: Occidente
CIUDAD: Cali
CÓDIGO SERVICIO: I9F
SERIAL ONT: 6C10412FAEF7
MAC ONT:
ANCHO DE BANDA: 950
NOMBRE TÉCNICO: Sergio Cuellar
CELULAR TÉCNICO: 3132468923

ALIADO: CONECTAR
TIPO ACTIVIDAD: Instalación Nueva
REQUIERE IP BRIDGE? SI
REQUIERE DMZ? NO

FECHA SOLICITUD:
"""


class PruebasReporte(unittest.TestCase):
    def test_datos_para_reportar(self):
        self.assertEqual(P.datos_reporte(SOLICITUD), "RR: 64767642\nREGIONAL: Occidente\nALIADO: CONECTAR")

    def test_campos(self):
        s = P.parsear_solicitud(SOLICITUD)
        self.assertEqual((s["regional"], s["aliado"], s["solicitud_id"], s["bridge"]),
                         ("Occidente", "CONECTAR", "65079", True))

    def test_sin_datos(self):
        self.assertEqual(P.datos_reporte(""), "RR: \nREGIONAL: \nALIADO: ")


class PruebasNombreCliente(unittest.TestCase):
    def test_como_el_script(self):
        self.assertEqual(P.descripcion_cliente("Danner Arias", "1232131"), "DANNER_ARIAS_1232131")
        self.assertEqual(P.descripcion_cliente("  José  Peña  ", "64767642.0000000"), "JOSE_PENA_64767642")
        self.assertEqual(P.descripcion_cliente("AGRICOLA A UTOMOTRIZ SAS", "64767642"),
                         "AGRICOLA_A_UTOMOTRIZ_SAS_64767642")
        self.assertEqual(P.descripcion_cliente("", "1"), "")

    def test_con_bridge(self):
        self.assertEqual(P.con_bridge("DANNER_ARIAS_1232131"), "DANNER_ARIAS_1232131_BRIDGE")
        self.assertEqual(P.con_bridge(""), "")


if __name__ == "__main__":
    unittest.main()
