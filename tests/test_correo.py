# -*- coding: utf-8 -*-
"""Pruebas del lector de correo (sin Outlook) y de la opcion Ver navegador."""
import json
import os
import sys
import tempfile
import unittest

os.environ["HAC_ZAC_DATOS"] = tempfile.mkdtemp(prefix="hz_correo_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import correo_lector  # noqa: E402
import navegador  # noqa: E402
from hac_zac import cola  # noqa: E402


def correo(id_, rr="64192718.0000000"):
    return "++++++SOLICITUD ID: %s++++++\nPROPIEDAD RED: CLARO\nCUENTA RR: %s\nFECHA SOLICITUD:" % (id_, rr)


class PruebasCorreo(unittest.TestCase):
    def test_elige_solo_el_id_correcto(self):
        textos = [(correo("64500"), None), (correo("64512"), "2026-11-13T10:00:00"), (correo("64513"), None)]
        r = correo_lector.elegir_correo("64512", 3, lambda i: textos[i], log=lambda m: None)
        self.assertIn("SOLICITUD ID: 64512", r[0])
        self.assertEqual(r[1], "2026-11-13T10:00:00")

    def test_otro_id_no_se_carga(self):
        avisos = []
        r = correo_lector.elegir_correo("64512", 2, lambda i: (correo("64500"), None), log=avisos.append)
        self.assertIsNone(r)
        self.assertIn("64500", avisos[0])

    def test_correos_que_no_son_solicitud_se_saltan(self):
        r = correo_lector.elegir_correo("1", 2, lambda i: ("hola " + str(i), None), log=lambda m: None)
        self.assertIsNone(r)

    def test_conversacion_con_varios_mensajes_toma_el_del_id(self):
        textos = ["RE: gracias", correo("64500"), correo("64512")]
        self.assertIn("64512", correo_lector.elegir_texto(textos, "64512"))

    def test_conversacion_sin_el_id_devuelve_una_solicitud(self):
        self.assertIn("64500", correo_lector.elegir_texto(["hola", correo("64500")], "1"))
        self.assertEqual(correo_lector.elegir_texto(["hola"], "1"), "hola")
        self.assertEqual(correo_lector.elegir_texto([], "1"), "")
        self.assertEqual(correo_lector.elegir_texto(correo("7"), "7"), correo("7"))

    def test_esperar_reintenta_hasta_que_aparece(self):
        vals = iter([None, [], ["fila"]])
        r = correo_lector.esperar(lambda: next(vals), 5, dormir=lambda s: None)
        self.assertEqual(r, ["fila"])

    def test_esperar_respeta_el_maximo(self):
        llamadas = []
        r = correo_lector.esperar(lambda: llamadas.append(1), 2, paso=0.5, dormir=lambda s: None)
        self.assertIsNone(r)
        self.assertEqual(len(llamadas), 5)       # 1 inicial + 4 reintentos de 0.5 s


class FalsoElemento:
    def __init__(self, convid="", etiqueta="", visible=True):
        self.a = {"data-convid": convid, "aria-label": etiqueta}
        self.text = etiqueta
        self.visible = visible

    def get_attribute(self, n):
        return self.a.get(n)

    def is_displayed(self):
        return self.visible


class FalsoOutlook:
    def __init__(self, por_selector):
        self.por_selector = por_selector

    def find_elements(self, by, css):
        return self.por_selector.get(css, [])


class PruebasSelectores(unittest.TestCase):
    def test_resultados_usa_el_primer_selector_con_filas(self):
        fila = FalsoElemento("c1", "De: X")
        d = FalsoOutlook({correo_lector.SEL_RESULTADOS[1]: [fila], correo_lector.SEL_RESULTADOS[-1]: [1, 2]})
        self.assertEqual(correo_lector._resultados(d), [fila])

    def test_sin_filas_lista_vacia_y_firma_vacia(self):
        d = FalsoOutlook({})
        self.assertEqual(correo_lector._resultados(d), [])
        self.assertEqual(correo_lector._firma(d), "")

    def test_firma_cambia_con_otra_lista(self):
        css = correo_lector.SEL_RESULTADOS[0]
        a = correo_lector._firma(FalsoOutlook({css: [FalsoElemento("c1", "uno")]}))
        b = correo_lector._firma(FalsoOutlook({css: [FalsoElemento("c2", "dos")]}))
        self.assertNotEqual(a, b)

    def test_buscador_salta_los_ocultos(self):
        oculto, visible = FalsoElemento(visible=False), FalsoElemento()
        d = FalsoOutlook({correo_lector.CAJAS_BUSQUEDA[0]: [oculto], correo_lector.CAJAS_BUSQUEDA[3]: [visible]})
        self.assertIs(correo_lector._caja_busqueda(d), visible)


class FalsoDriver:
    def __init__(self):
        self.pos = None

    def set_window_position(self, x, y):
        self.pos = (x, y)


class PruebasVisibilidad(unittest.TestCase):
    def _ajustes(self, **kw):
        from hac_zac.rutas import data_dir
        (data_dir() / "ajustes.json").write_text(json.dumps(kw), encoding="utf-8")

    def test_por_defecto_se_ve(self):
        self._ajustes()
        self.assertTrue(navegador.ver_navegador("correo"))

    def test_oculta_y_muestra_en_vivo(self):
        d = FalsoDriver()
        self._ajustes(ver_sp=False)
        navegador.aplicar_visibilidad(d, "sp")
        self.assertEqual(d.pos, navegador.FUERA)
        self._ajustes(ver_sp=True)
        navegador.aplicar_visibilidad(d, "sp")
        self.assertEqual(d.pos, navegador.DENTRO)

    def test_forzar_muestra_aunque_este_oculto(self):
        d = FalsoDriver()
        self._ajustes(ver_sp=False)
        navegador.aplicar_visibilidad(d, "sp", forzar=True)
        self.assertEqual(d.pos, navegador.DENTRO)


class PruebasEstadoPorDocumentar(unittest.TestCase):
    def test_por_documentar_sigue_abierta(self):
        self.assertIn("por_documentar", cola.ABIERTOS)


if __name__ == "__main__":
    unittest.main()
