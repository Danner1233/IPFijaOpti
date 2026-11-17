# -*- coding: utf-8 -*-
"""Instalador: copia sin pisar datos del usuario, encuentra SecureCRT y la sesion del jump host, completa ajustes."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import instalar as I  # noqa: E402


def escribir(ruta, texto=""):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)


def sesion(carpeta, nombre, host):
    escribir(os.path.join(carpeta, nombre + ".ini"), 'S:"Protocol Name"=SSH2\nS:"Hostname"=%s\n' % host)


class PruebasCopia(unittest.TestCase):
    def test_instala_y_actualiza_sin_pisar_datos(self):
        o, d = tempfile.mkdtemp(), tempfile.mkdtemp()
        escribir(os.path.join(o, "hac_zac_gui.py"), "v2")
        escribir(os.path.join(o, "historial_capa2.json"), "{base nueva}")
        escribir(os.path.join(o, "python", "python.exe"), "exe")
        escribir(os.path.join(o, "solicitudes", "x.json"), "{de paquete}")
        escribir(os.path.join(d, "hac_zac_gui.py"), "v1")
        escribir(os.path.join(d, "historial_capa2.json"), "{mi base}")
        escribir(os.path.join(d, "solicitudes", "1.json"), "{mi solicitud}")
        copiados, conservados = I.copiar_programa(o, d)
        leer = lambda *p: open(os.path.join(d, *p), encoding="utf-8").read()  # noqa: E731
        self.assertEqual(leer("hac_zac_gui.py"), "v2", "el programa se actualiza")
        self.assertEqual(leer("historial_capa2.json"), "{mi base}", "los datos del usuario no")
        self.assertEqual(os.listdir(os.path.join(d, "solicitudes")), ["1.json"])
        self.assertTrue(os.path.isfile(os.path.join(d, "python", "python.exe")))
        self.assertEqual(conservados, 1)

    def test_primera_vez_si_copia_la_base(self):
        o, d = tempfile.mkdtemp(), tempfile.mkdtemp()
        escribir(os.path.join(o, "historial_capa2.json"), "{base}")
        I.copiar_programa(o, d)
        self.assertTrue(os.path.isfile(os.path.join(d, "historial_capa2.json")))


class PruebasSecureCRT(unittest.TestCase):
    def test_sesion_por_ip_prefiere_la_que_tiene_nombre(self):
        c = tempfile.mkdtemp()
        sesion(c, "172.31.238.6", I.JUMP_HOST)
        sesion(c, "HENDRIX_DEMIMASTER", I.JUMP_HOST)
        sesion(c, "OTRO", "10.0.0.1")
        self.assertEqual(I.buscar_sesion(c), "HENDRIX_DEMIMASTER")
        self.assertEqual(I.buscar_sesion(tempfile.mkdtemp()), "")

    def test_sesion_en_subcarpeta(self):
        c = tempfile.mkdtemp()
        sesion(os.path.join(c, "Claro"), "JUMP", I.JUMP_HOST)
        self.assertEqual(I.buscar_sesion(c), "Claro/JUMP")

    def test_entre_varias_copias_elige_la_del_jump_host_con_nombre(self):
        raiz = tempfile.mkdtemp()
        vieja = os.path.join(raiz, "viejo", "SecureCRTPortable.exe")
        buena = os.path.join(raiz, "nuevo", "SecureCRTPortable.exe")
        for exe, (nombre, host) in ((vieja, (I.JUMP_HOST, I.JUMP_HOST)), (buena, ("HENDRIX", I.JUMP_HOST))):
            escribir(exe)
            sesion(I.carpeta_sesiones(exe), nombre, host)
        os.utime(I.carpeta_sesiones(vieja), (time.time() + 99, time.time() + 99))   # la vieja "mas reciente"
        orig = I._candidatos_fijos
        I._candidatos_fijos = lambda: iter(())
        try:
            self.assertEqual(I.buscar_securecrt([raiz]), buena)
        finally:
            I._candidatos_fijos = orig


class PruebasAjustes(unittest.TestCase):
    def test_completa_solo_lo_vacio(self):
        d = tempfile.mkdtemp()
        escribir(os.path.join(d, "ajustes.json"), json.dumps({"sesion_crt": "MI_SESION", "pem_nombre": "Ana"}))
        aj = I.configurar(d, "C:/equipo", "C:/crt.exe", "OTRA")
        self.assertEqual((aj["sesion_crt"], aj["securecrt_exe"], aj["carpeta_equipo"], aj["pem_nombre"]),
                         ("MI_SESION", "C:/crt.exe", "C:/equipo", "Ana"))


class PruebasArmador(unittest.TestCase):
    def test_paquete_sin_pruebas_ni_pip(self):
        import armar_instalador as A
        progs = A.archivos_programa()
        self.assertIn("instalar.py", progs)
        self.assertIn("iniciar_hac_zac.py", progs)
        self.assertFalse([f for f in progs if f.startswith("tests/")])
        rutas = [d for _r, d in A.archivos_python(sys.base_prefix)]
        self.assertTrue(any(r.endswith(os.path.join("python", "python.exe")) for r in rutas))
        self.assertFalse([r for r in rutas if os.sep + "pip" + os.sep in r])


if __name__ == "__main__":
    unittest.main()
