# -*- coding: utf-8 -*-
"""Pruebas del núcleo (sin interfaz, sin red, sin SecureCRT).

Ejecutar desde la carpeta del programa:   python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

# carpeta de datos temporal: las pruebas nunca tocan los datos reales
os.environ["HAC_ZAC_DATOS"] = tempfile.mkdtemp(prefix="hz_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hac_zac import cola  # noqa: E402
from hac_zac import plantilla as pl  # noqa: E402

FILA_64418 = ("64418\t12/11/2026 2:02p. m.;2026-11-12T19:02:04Z\tDanner Arias\tAsignada\t\t\t\tCLARO\t64.184.491\t"
              "CASA ILUMI NA S A S\t481960900\t68:2A:DD:97:2B:EB\tAntioquia\tMedellín \tCINCO\tNo\tSI\t"
              "Instalación Nueva\tI9F\t\t950\t\tCarlos Andrés yopasa \t3105912483\tNO")

CORREO = """++++++SOLICITUD ID: 64347++++++
PROPIEDAD RED: CLARO
CUENTA RR: 64256836.0000000
CÓDIGO SERVICIO: I2F
SERIAL ONT: 6C:10:41:2F:2A:1F
MAC ONT:
ANCHO DE BANDA: 999
REQUIERE IP BRIDGE? NO
"""


class PruebasPlantilla(unittest.TestCase):
    def test_fila_sharepoint_se_reconoce(self):
        self.assertTrue(pl.es_fila_sp(FILA_64418))
        self.assertFalse(pl.es_fila_sp(CORREO))

    def test_fila_sharepoint_datos(self):
        r = pl.parsear_solicitud(FILA_64418)
        self.assertEqual(r["solicitud_id"], "64418")
        self.assertEqual(r["rr"], "64184491")
        self.assertEqual(r["mac_ont"], "68:2A:DD:97:2B:EB")
        self.assertEqual(r["ancho_banda"], "950")
        self.assertTrue(r["bridge"])

    def test_tipo_actividad_tal_cual(self):
        self.assertIn("TIPO ACTIVIDAD: Instalación Nueva", pl.desde_fila_sp(FILA_64418))

    def test_megas_salen_del_codigo_no_del_numero(self):
        self.assertEqual(pl.parsear_solicitud(CORREO)["ancho_banda"], "250")      # I2F, aunque diga 999
        self.assertEqual(pl.megas_por_codigo("i9p"), "300")
        self.assertEqual(pl.megas_por_codigo("XXX"), "")

    def test_mac_en_casilla_de_serial(self):
        r = pl.parsear_solicitud(CORREO)
        self.assertEqual(pl.normalizar_sn(r["serial_ont"]), "6C10412F2A1F")

    def test_direccionamiento_sin_y_con_bridge(self):
        d = pl.DatosPlantilla(solicitud_id="1", rr="2", ip="10.0.0.5", mascara="255.255.255.0",
                              gateway="10.0.0.1", capa2="ZAC-X", capa2_ip="172.30.1.1")
        sin = pl.construir_direccionamiento(d)
        self.assertNotIn("-------Bridge--------", sin)
        self.assertIn("ZAC-X - 172.30.1.1", sin)
        d.ip_bridge = "10.0.0.6"
        self.assertIn("-------Bridge--------", pl.construir_direccionamiento(d))


class PruebasCola(unittest.TestCase):
    def test_libre_solo_si_pem_vacio(self):
        libre = {"ID": 1, "Created": "2026-11-12T15:00:00Z", "PEM_ASIGNADO": None, "Est_Seg": "Sin Asignar", "ActivApoyo": "No"}
        ocupada = dict(libre, ID=2, PEM_ASIGNADO="Otro Ing", Est_Seg="Asignada")
        cerrada = dict(libre, ID=3, Est_Seg="Exitosa")
        self.assertTrue(cola.es_libre(libre))
        self.assertFalse(cola.es_libre(ocupada))
        self.assertFalse(cola.es_libre(cerrada))

    def test_elige_la_mas_antigua(self):
        a = {"ID": 1, "Created": "2026-11-12T15:00:00Z", "PEM_ASIGNADO": "", "Est_Seg": None, "ActivApoyo": "No"}
        b = dict(a, ID=2, Created="2026-11-12T14:00:00Z")
        self.assertEqual(cola.elegir_libre([a, b])["ID"], 2)

    def test_solo_digitos_no_agrega_ceros(self):
        self.assertEqual(cola.solo_digitos(64270704.0), "64270704")
        self.assertEqual(cola.solo_digitos("64.256.836"), "64256836")

    def test_bloqueo_no_pierde_escrituras_concurrentes(self):
        for i in range(12):
            threading.Thread(target=lambda n=i: cola.agregar_ingeniero("Ing %d" % n)).start()
        for t in threading.enumerate():
            if t is not threading.current_thread():
                t.join(10)
        nombres = {x["nombre"] for x in cola.ingenieros()}
        self.assertEqual(len([n for n in nombres if n.startswith("Ing ")]), 12)


class PruebasCorreoActual(unittest.TestCase):
    def test_descarta_correos_de_cuentas_viejas(self):
        base = datetime.now(timezone.utc).replace(microsecond=0)
        sol = {"datos": {"creada": base.isoformat().replace("+00:00", "Z")}, "recibida": ""}
        vieja = (base - timedelta(days=3)).isoformat()
        nueva = (base + timedelta(minutes=3)).isoformat()
        self.assertFalse(cola.correo_es_actual(sol, vieja))
        self.assertTrue(cola.correo_es_actual(sol, nueva))
        self.assertIsNone(cola.correo_es_actual(sol, None))


if __name__ == "__main__":
    unittest.main()


class PruebasExtraerSolicitud(unittest.TestCase):
    def test_solo_el_bloque_de_la_solicitud(self):
        t = ("--- DATOS DE CONFIGURACIÓN ---\n\nCONFIGURADOR: X\n\n++++++SOLICITUD ID: 64512++++++\n\n"
             "NODO: HOEN23\nCUENTA RR: 1\nFECHA SOLICITUD:   \n\nPing results\nlinea extra\n")
        r = pl.extraer_solicitud(t)
        self.assertTrue(r.startswith("++++++SOLICITUD ID: 64512"))
        self.assertTrue(r.endswith("FECHA SOLICITUD:"))
        self.assertNotIn("CONFIGURADOR", r)
        self.assertNotIn("Ping", r)

    def test_sin_inicio_devuelve_el_texto(self):
        self.assertEqual(pl.extraer_solicitud("  hola  "), "hola")


class PruebasEstadoSharePoint(unittest.TestCase):
    NOMBRE = "Danner Arias Munive"

    def _item(self, id_, estado, pem=None, horas=1):
        creada = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"ID": id_, "Created": creada, "PEM_ASIGNADO": pem, "Est_Seg": estado, "ActivApoyo": "No"}

    def setUp(self):
        try:
            os.remove(str(cola._ruta(cola.SP_PENDIENTES)))
        except OSError:
            pass

    def test_asignada_sin_documentar_bloquea(self):
        items = [self._item(1, "Asignada", "Danner Arias Munive")]
        self.assertEqual(cola.abiertas_sp(items, self.NOMBRE), ["1"])

    def test_estados_finales_permiten_asignar(self):
        for e in ("Exitosa", "No exitosa", "Escalamiento"):
            items = [self._item(1, e, "Danner Arias Munive")]
            self.assertEqual(cola.abiertas_sp(items, self.NOMBRE), [], e)

    def test_ajenas_y_viejas_no_bloquean(self):
        items = [self._item(1, "Asignada", "Otro Ingeniero"), self._item(2, "Asignada", "Danner Arias Munive", horas=40)]
        self.assertEqual(cola.abiertas_sp(items, self.NOMBRE), [])

    def test_documentar_libera_aunque_sp_no_acepte(self):
        items = [self._item(1, "Asignada", "Danner Arias Munive")]
        cola.pedir_estado_sp("1", "Exitosa")
        self.assertEqual(cola.pendientes_sp(), {"1": "Exitosa"})
        self.assertEqual(cola.abiertas_sp(items, self.NOMBRE), [])        # ya documentada: no bloquea
        for _ in range(cola.MAX_INTENTOS_SP):
            cola.resultado_sp("1", False, "error")
        self.assertEqual(cola.pendientes_sp(), {})                          # deja de reintentar
        cola.pedir_estado_sp("2", "Escalamiento")
        cola.resultado_sp("2", True)
        self.assertEqual(cola.pendientes_sp(), {})


class PruebasSesion(unittest.TestCase):
    def test_caso_pasa_a_la_ventana_viva(self):
        from hac_zac import sesion
        sesion.apagar()
        self.assertFalse(sesion.hay_ventana_viva())
        sesion.latir()
        self.assertTrue(sesion.hay_ventana_viva())
        sesion.enviar_caso({"id": "7", "txt_sol": "x"})
        self.assertEqual(sesion.tomar_caso()["id"], "7")
        self.assertIsNone(sesion.tomar_caso())
        sesion.apagar()


FILA_64564 = ("64564\t13/11/2026 11:48a. m.;2026-11-13T16:48:52Z\tDanner Arias\tAsignada\t\t\t\tCLARO\t64.388.571\t"
              "GUB A S A S\t482168442\tZTEGDE4E611B\tOccidente\tIbague\tCONECTAR\tNo\tNO\tInstalación Nueva\tI9F\t\t950\t\t"
              "John Adalver Lopez Gantiva\t3223643059\tNO\t\t\tNo\t64.388.571")


class PruebasFilaConSerial(unittest.TestCase):
    """Fila de SharePoint con SERIAL en lugar de MAC (solicitud 64564): antes quedaban vacios regional, ciudad, etc."""

    def test_campos_despues_del_serial(self):
        t = pl.desde_fila_sp(FILA_64564)
        for esperado in ("SERIAL ONT: ZTEGDE4E611B", "REGIONAL: Occidente", "CIUDAD: Ibague", "ALIADO: CONECTAR",
                         "TIPO ACTIVIDAD: Instalación Nueva", "CÓDIGO SERVICIO: I9F", "ANCHO DE BANDA: 950",
                         "NOMBRE TÉCNICO: John Adalver Lopez Gantiva", "CELULAR TÉCNICO: 3223643059",
                         "REQUIERE IP BRIDGE? NO", "REQUIERE DMZ? NO"):
            self.assertIn(esperado, t)
