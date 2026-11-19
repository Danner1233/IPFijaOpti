# -*- coding: utf-8 -*-
"""SCOM… es serial (no MAC) y la solicitud se copia sin lineas en blanco de sobra."""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_sf_"))
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from hac_zac import plantilla as P  # noqa: E402
import hac_zac_gui as gui  # noqa: E402

# como llega de Outlook (con la linea del remitente y blancos de sobra)
CRUDA = (
    "Danner Arias\n\n++++++SOLICITUD ID: 65164++++++\n\n\n\n\nTIPO SOLICITUD CONFIG:\n\nPROPIEDAD RED: CLARO\n\n\n\n\n"
    "SERVICIO SOBRE ATP:\n\nNAP ATP:\n\nDIRECCIÓN CLIENTE:\n\nID HANDLE:\n\nID RESERVA ATP:\n\nID SERVICIO ATP:\n\n\n\n\n"
    "SERVICIO SOBRE ONNET:\nNAP ONNET:\nDIRECCIÓN CLIENTE:\nPLACE ID:\nID RESERVA ONNET:\nID SERVICIO ONNET:\n\n\n\n\n\n"
    "NODO: RP2\n\nCUENTA RR: 2637758.00000000\nOT/LLs RR: 482460408\nNOMBRE CLIENTE: AINKAA S A S\n"
    "REGIONAL: Centro\nCIUDAD: Bogotá\nCÓDIGO SERVICIO: I9F\nSERIAL ONT: SCOMA0B03D18\nMAC ONT:\n"
    "ANCHO DE BANDA: 950\nNOMBRE TÉCNICO: Brayan Samuel Sandoval cañas\nCELULAR TÉCNICO: 3106005658\n\n"
    "ALIADO: TABASCO\nTIPO ACTIVIDAD: Brownfield\nREQUIERE IP BRIDGE? SI\nREQUIERE DMZ? NO\nIP PRIVADA 1:\n"
    "REQUIERE PORT FW? No\nIP PRIVADA 1:\nPUERTO INTERNO 1:\nPUERTO EXTERNO 1:  \n\n\n\n\n"
    "CANTIDAD DE IPs A CONFIGURAR: 1\n\n\n\n\n\n\nFECHA SOLICITUD:\n")

# como la pidio Danner
ESPERADA = """++++++SOLICITUD ID: 65164++++++


TIPO SOLICITUD CONFIG:

PROPIEDAD RED: CLARO

SERVICIO SOBRE ATP:
NAP ATP:
DIRECCIÓN CLIENTE:
ID HANDLE:
ID RESERVA ATP:
ID SERVICIO ATP:
SERVICIO SOBRE ONNET:
NAP ONNET:
DIRECCIÓN CLIENTE:
PLACE ID:
ID RESERVA ONNET:
ID SERVICIO ONNET:
NODO: RP2

CUENTA RR: 2637758.00000000
OT/LLs RR: 482460408
NOMBRE CLIENTE: AINKAA S A S
REGIONAL: Centro
CIUDAD: Bogotá
CÓDIGO SERVICIO: I9F
SERIAL ONT: SCOMA0B03D18
MAC ONT:
ANCHO DE BANDA: 950
NOMBRE TÉCNICO: Brayan Samuel Sandoval cañas
CELULAR TÉCNICO: 3106005658

ALIADO: TABASCO
TIPO ACTIVIDAD: Brownfield
REQUIERE IP BRIDGE? SI
REQUIERE DMZ? NO
IP PRIVADA 1:
REQUIERE PORT FW? No
IP PRIVADA 1:
PUERTO INTERNO 1:
PUERTO EXTERNO 1:

CANTIDAD DE IPs A CONFIGURAR: 1

FECHA SOLICITUD:"""


class PruebasFormato(unittest.TestCase):
    def test_copiar_queda_compacta(self):
        self.assertEqual(P.extraer_solicitud(CRUDA), ESPERADA)

    def test_ya_compacta_no_cambia(self):
        self.assertEqual(P.extraer_solicitud(ESPERADA), ESPERADA)
        self.assertEqual(P.compactar_solicitud(ESPERADA), ESPERADA)

    def test_compactar_deja_lo_de_alrededor(self):
        t = "DATOS DE CONFIGURACION\nCONFIGURADOR: X\n\n" + CRUDA.split("Danner Arias\n\n")[1] + "\nPing: ok\n"
        r = P.compactar_solicitud(t)
        self.assertTrue(r.startswith("DATOS DE CONFIGURACION\nCONFIGURADOR: X\n\n" + ESPERADA))
        self.assertTrue(r.endswith("\nPing: ok\n"))

    def test_en_la_plantilla(self):
        d = P.DatosPlantilla(configurador="DANNER", solicitud=CRUDA.split("Danner Arias\n\n")[1])
        self.assertIn(ESPERADA, P._encabezado(d))

    def test_los_datos_se_siguen_leyendo(self):
        s = P.parsear_solicitud(P.extraer_solicitud(CRUDA))
        self.assertEqual((s["solicitud_id"], s["rr"], s["serial_ont"], s["bridge"]),
                         ("65164", "2637758", "SCOMA0B03D18", True))


class PruebasSerialMac(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("# Prefijos de SERIAL")
        j = src.index("def solo_ascii")
        ns = {"re": __import__("re")}
        exec(src[i:j], ns)                      # es_mac() del script (py2.7/py3)
        self.es_mac = ns["es_mac"]

    def test_scom_es_serial(self):
        self.assertFalse(self.es_mac("SCOMA0B03D18"))
        self.assertEqual(gui.tipo_valor("SCOMA0B03D18"), "SERIAL")

    def test_macs(self):
        for m in ("6C10412FAEF7", "68:2a:dd:98:fe:3b", "30-F9-47-BC-76-F2"):
            self.assertTrue(self.es_mac(m), m)
            self.assertEqual(gui.tipo_valor(m), "MAC", m)

    def test_seriales(self):
        for s in ("ZTEGC8A1B2C3", "HWTC12345678", "SEI12345678", "FHTT1234ABCD", "ALCLB1234567", "XYZ999"):
            self.assertFalse(self.es_mac(s), s)
            self.assertEqual(gui.tipo_valor(s), "SERIAL", s)


if __name__ == "__main__":
    unittest.main()
