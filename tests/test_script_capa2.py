# -*- coding: utf-8 -*-
"""obtener_capa2 del script de SecureCRT (se extrae la funcion del archivo: el script necesita SecureCRT para
importarse completo)."""
import ast
import io
import os
import re
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cargar(nombre):
    with io.open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    nodo = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == nombre)
    espacio = {"re": re}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), "script", "exec"), espacio)
    return espacio[nombre]


obtener_capa2 = _cargar("obtener_capa2")


def config(desc):
    return ("dis cur int Vlanif2345\n#\ninterface Vlanif2345\n description %s\n"
            " ip address 10.20.30.1 255.255.255.248\n#\nreturn\n<CAPA3>" % desc)


class PruebasCapa2(unittest.TestCase):
    def test_onnet_oh(self):
        self.assertEqual(obtener_capa2(config("OH_BOGALGDOH_I_7360_CentrodeGravedad2_8")),
                         ("OH", "OH_BOGALGDOH_I_7360_CentrodeGravedad2_8"))

    def test_onnet_oh_con_texto_alrededor(self):
        self.assertEqual(obtener_capa2(config("TO_OH_BOGALGDOH_I_7360_CentrodeGravedad2_8 (IP FIJA)")),
                         ("OH", "OH_BOGALGDOH_I_7360_CentrodeGravedad2_8"))
        self.assertEqual(obtener_capa2(config("OH-MEDALG_7360_Poblado_3"))[0], "OH")

    def test_zac_y_hac_siguen_igual(self):
        self.assertEqual(obtener_capa2(config("ZAC_BOG_CHAPINERO_01")), ("ZAC", "ZAC_BOG_CHAPINERO_01"))
        self.assertEqual(obtener_capa2(config("TO-HAC-MED-ENVIGADO-2")), ("HAC", "HAC-MED-ENVIGADO-2"))

    def test_zac_tiene_prioridad_sobre_oh(self):
        self.assertEqual(obtener_capa2(config("OH_ALGO ZAC_BOG_01"))[0], "ZAC")

    def test_no_confunde_palabras_con_oh_en_medio(self):
        self.assertEqual(obtener_capa2(config("JOHN_TEST OHM_LINK")), (None, None))
        self.assertEqual(obtener_capa2(config("BOGALGDOH_I_7360")), (None, None))

    def test_sin_description(self):
        self.assertEqual(obtener_capa2("interface Vlanif1\n ip address 1.1.1.1 255.255.255.0"), (None, None))


if __name__ == "__main__":
    unittest.main()
