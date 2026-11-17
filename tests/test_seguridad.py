# -*- coding: utf-8 -*-
"""Credenciales cifradas, nada de claves en el codigo y auditoria de escrituras en SharePoint."""
import io
import json
import os
import re
import sys
import tempfile
import unittest

os.environ["HAC_ZAC_DATOS"] = tempfile.mkdtemp(prefix="hz_seg_")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import hac_zac_dpapi as dpapi  # noqa: E402
from hac_zac import cola, credenciales  # noqa: E402
from hac_zac.rutas import data_dir  # noqa: E402
from hac_zac.servicio import Servicio  # noqa: E402


class PruebasSinClavesEnCodigo(unittest.TestCase):
    def test_script_no_trae_credenciales(self):
        with io.open(os.path.join(RAIZ, "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8") as f:
            s = f.read()
        for var in ("USUARIO", "CLAVE", "PORTAL_USUARIO", "PORTAL_CLAVE"):
            m = re.search(r'(?m)^%s = "([^"]*)"' % var, s)
            self.assertIsNotNone(m, var)
            self.assertEqual(m.group(1), "", "%s debe ir vacio: las credenciales van en Ajustes" % var)

    def test_datos_fuera_del_repo(self):
        with io.open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8") as f:
            ign = f.read().split()
        for f in ("historial_capa2.json", "credenciales.json", "ajustes.json", "registro_sharepoint.jsonl"):
            self.assertIn(f, ign)


@unittest.skipUnless(dpapi.disponible(), "DPAPI solo en Windows")
class PruebasCifrado(unittest.TestCase):
    def test_ida_y_vuelta(self):
        c = dpapi.cifrar(u"clave-ñ-1")
        self.assertTrue(c.startswith(dpapi.PREFIJO))
        self.assertNotIn(u"clave", c)
        self.assertEqual(dpapi.descifrar(c), u"clave-ñ-1")

    def test_texto_plano_viejo_se_respeta(self):
        self.assertEqual(dpapi.descifrar("plana"), "plana")
        self.assertEqual(dpapi.cifrar(""), "")

    def test_guardar_cifra_solo_las_claves(self):
        credenciales.guardar({"crt_usuario": "u1", "crt_clave": "secreta", "ms_usuario": "a@b.co"})
        raw = json.loads(credenciales.ruta().read_text(encoding="utf-8"))
        self.assertEqual(raw["crt_usuario"], "u1")
        self.assertTrue(raw["crt_clave"].startswith("dpapi:"))
        self.assertNotIn("secreta", credenciales.ruta().read_text(encoding="utf-8"))
        self.assertEqual(credenciales.cargar()["crt_clave"], "secreta")

    def test_archivo_viejo_se_cifra_al_cargar(self):
        credenciales.ruta().write_text(json.dumps({"portal_clave": "vieja"}), encoding="utf-8")
        self.assertEqual(credenciales.cargar()["portal_clave"], "vieja")
        raw = json.loads(credenciales.ruta().read_text(encoding="utf-8"))
        self.assertTrue(raw["portal_clave"].startswith("dpapi:"))

    def test_clave_danada_queda_vacia_sin_romper(self):
        credenciales.ruta().write_text(json.dumps({"crt_clave": "dpapi:AAAA"}), encoding="utf-8")
        self.assertEqual(credenciales.cargar()["crt_clave"], "")


class PruebasAuditoriaSP(unittest.TestCase):
    def setUp(self):
        p = data_dir() / cola.REGISTRO_SP
        if p.exists():
            p.unlink()

    def test_registra_antes_y_despues(self):
        cola.registrar_escritura_sp("64512", "Est_Seg", "Asignada", "Exitosa", True)
        cola.registrar_escritura_sp("64513", "Est_Seg", "", "Escalamiento", False, "412")
        r = cola.leer_registro_sp()
        self.assertEqual(len(r), 2)
        self.assertEqual((r[0]["id"], r[0]["antes"], r[0]["despues"], r[0]["ok"]), ("64512", "Asignada", "Exitosa", True))
        self.assertFalse(r[1]["ok"])
        self.assertEqual(r[1]["motivo"], "412")

    def test_sin_registro_lista_vacia(self):
        self.assertEqual(cola.leer_registro_sp(), [])

    def test_estado_que_quedara_en_sharepoint(self):
        self.assertEqual(Servicio.estado_sp_de({"id": "7", "resultado": "exitosa"}), ("7", "Exitosa"))
        self.assertIsNone(Servicio.estado_sp_de({"id": "8"}), "sin estado confirmado no se escribe nada (caso 64849)")
        self.assertIsNone(Servicio.estado_sp_de({}))


if __name__ == "__main__":
    unittest.main()
