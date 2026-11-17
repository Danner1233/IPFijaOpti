# -*- coding: utf-8 -*-
"""El perfil del navegador de Forms vive fuera de OneDrive y se migra el viejo sin perder la sesion."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import forms_bot  # noqa: E402


class PruebasPerfilForms(unittest.TestCase):
    def setUp(self):
        self.local = tempfile.mkdtemp(prefix="hz_local_")
        self.datos = tempfile.mkdtemp(prefix="hz_datos_")
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.local, "HAC_ZAC_DATOS": self.datos})
        self.env.start()
        self.nuevo = os.path.join(self.local, "hac_zac", "perfil_forms")

    def tearDown(self):
        self.env.stop()

    def _perfil_viejo(self):
        viejo = os.path.join(self.datos, "browser_profile")
        os.makedirs(os.path.join(viejo, "Default", "Network"))
        os.makedirs(os.path.join(viejo, "Default", "Cache"))
        with open(os.path.join(viejo, "Default", "Network", "Cookies"), "w") as f:
            f.write("sesion")
        with open(os.path.join(viejo, "Default", "Cache", "basura"), "w") as f:
            f.write("x")
        with open(os.path.join(viejo, "SingletonLock"), "w") as f:
            f.write("candado")
        return viejo

    def test_queda_fuera_de_onedrive_en_localappdata(self):
        r = forms_bot.perfil_forms()
        self.assertEqual(r, self.nuevo)
        self.assertTrue(os.path.isdir(r))
        self.assertNotIn("OneDrive", r.replace(self.local, ""))

    def test_migra_la_sesion_sin_cache_ni_candados(self):
        viejo = self._perfil_viejo()
        r = forms_bot.perfil_forms()
        self.assertTrue(os.path.isfile(os.path.join(r, "Default", "Network", "Cookies")))
        self.assertFalse(os.path.exists(os.path.join(r, "Default", "Cache")))
        self.assertFalse(os.path.exists(os.path.join(r, "SingletonLock")))
        self.assertTrue(os.path.isdir(viejo), "el perfil viejo se deja intacto")

    def test_no_pisa_un_perfil_nuevo_que_ya_existe(self):
        os.makedirs(self.nuevo)
        self._perfil_viejo()
        forms_bot.perfil_forms()
        self.assertFalse(os.path.exists(os.path.join(self.nuevo, "Default")))

    def test_si_la_copia_falla_queda_un_perfil_limpio(self):
        self._perfil_viejo()
        with mock.patch("shutil.copytree", side_effect=OSError("bloqueado")):
            r = forms_bot.perfil_forms()
        self.assertTrue(os.path.isdir(r))
        self.assertEqual(os.listdir(r), [])


if __name__ == "__main__":
    unittest.main()
