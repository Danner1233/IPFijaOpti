# -*- coding: utf-8 -*-
"""Fase 2: el central lee UN buzon, une cada correo con su asignacion (por SOLICITUD ID) y la entrega al PEM."""
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_cc_"))
import correo_lector  # noqa: E402
import servidor_central as S  # noqa: E402
from hac_zac import central_cliente as CC, cola, reparto as R  # noqa: E402

T0 = datetime(2026, 11, 17, 8, 0, 0)


def item(id_, rr):
    return {"ID": id_, "Created": "2026-11-17T12:00:00Z", "PEM_ASIGNADO": "", "Est_Seg": "", "field_1": rr,
            "field_2": "Cliente %d" % id_, "ActivApoyo": ""}


def correo(id_, rr):
    return ("++++++SOLICITUD ID: %s++++++\nPROPIEDAD RED: CLARO\nCUENTA RR: %s\nNOMBRE CLIENTE: CLIENTE %s\n"
            "SERIAL ONT: ZTEGC0000%s\nANCHO DE BANDA: 300\nFECHA SOLICITUD:" % (id_, rr, id_, id_))


class FilaFalsa:
    def __init__(self, n, al_click):
        self.n, self.al_click, self.text = n, al_click, "De: Solicitudes 17/11/2026 10:0%d" % n

    def get_attribute(self, a):
        return self.text if a == "aria-label" else None

    def click(self):
        self.al_click(self.n)


class OutlookFalso:
    """Simula la busqueda por RR: devuelve los correos de esa cuenta (el mas nuevo primero)."""

    def __init__(self, buzon):
        self.buzon, self.rr, self.abierto = buzon, None, None

    def parchear(self):
        return [mock.patch.object(correo_lector, "_buscar_rr", lambda d, rr: setattr(self, "rr", rr)),
                mock.patch.object(correo_lector, "_resultados",
                                  lambda d: [FilaFalsa(i, lambda n: setattr(self, "abierto", n))
                                             for i, _ in enumerate(self.buzon.get(self.rr, []))]),
                mock.patch.object(correo_lector, "_leer_panel",
                                  lambda d, antes="": [self.buzon[self.rr][self.abierto]])]


class PruebasReparto(unittest.TestCase):
    def test_pendientes_y_entrega_con_correo(self):
        e = R.nuevo_estado()
        R.agregar_pem(e, "Ana Uno")
        R.registrar_asignacion(e, item(1, "64192718"), "Ana Uno", T0)
        R.registrar_asignacion(e, item(2, "55500011"), "Ana Uno", T0)
        self.assertEqual(set(R.pendientes_correo(e)), {"64192718", "55500011"})
        self.assertTrue(R.guardar_correo(e, "1", "texto", "2026-11-17T10:03:00"))
        self.assertFalse(R.guardar_correo(e, "99", "texto", None))
        self.assertEqual(set(R.pendientes_correo(e)), {"55500011"})
        casos, _ = R.latido(e, "Ana Uno", True, {}, T0)
        por_id = {c["id"]: c for c in casos}
        self.assertEqual(por_id["1"]["_correo"]["texto"], "texto")
        self.assertNotIn("_correo", por_id["2"])
        self.assertNotIn("_correo", e["asignaciones"]["1"]["datos"], "no ensucia los datos guardados")
        R.latido(e, "Ana Uno", True, {"2": "Exitosa"}, T0)
        self.assertEqual(R.pendientes_correo(e), {}, "una documentada ya no se busca")


class PruebasLectorCentral(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hz_lc_")
        self.env = mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": self.dir})
        self.env.start()
        self.c = S.Central(self.dir)
        R.agregar_pem(self.c.estado, "Ana Uno")
        R.registrar_asignacion(self.c.estado, item(64512, "64192718"), "Ana Uno", T0)

    def tearDown(self):
        self.env.stop()

    def _revisar(self, buzon):
        o = OutlookFalso(buzon)
        ps = o.parchear()
        for p in ps:
            p.start()
        try:
            return correo_lector.revisar(None, pendientes=self.c.pendientes_correo(), guardar=self.c.guardar_correo)
        finally:
            for p in ps:
                p.stop()

    def test_guarda_solo_el_correo_con_el_mismo_id(self):
        # misma cuenta RR: un correo viejo (otro ID) y el de esta solicitud
        n = self._revisar({"64192718": [correo(64000, "64192718"), correo(64512, "64192718")]})
        self.assertEqual(n, 1)
        a = self.c.estado["asignaciones"]["64512"]
        self.assertIn("SOLICITUD ID: 64512", a["correo"]["texto"])
        self.assertEqual(a["correo"]["recibido"][:10], "2026-11-17")
        self.assertEqual(self.c.pendientes_correo(), {})

    def test_si_aun_no_llega_sigue_pendiente(self):
        self.assertEqual(self._revisar({"64192718": [correo(64000, "64192718")]}), 0)
        self.assertEqual(self._revisar({}), 0)
        self.assertIn("64192718", self.c.pendientes_correo())

    def test_no_toca_la_cola_del_pc_central(self):
        self._revisar({"64192718": [correo(64512, "64192718")]})
        self.assertEqual(cola.solicitudes(), [])


class PruebasEntregaAlPEM(unittest.TestCase):
    def test_por_http_llega_el_caso_y_luego_su_plantilla(self):
        dir_c, dir_p = tempfile.mkdtemp(prefix="hz_c_"), tempfile.mkdtemp(prefix="hz_p_")
        with mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": dir_c}):
            c = S.Central(dir_c)
            c.correo_activo = True
            tok = R.agregar_pem(c.estado, "Ana Uno")
            srv = S.crear_servidor(c, puerto=0, host="127.0.0.1")
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            url = "http://127.0.0.1:%d" % srv.server_address[1]
            try:
                CC.enviar_latido(url, tok, True, {})
                c.repartir([item(64512, "64192718")], lambda *a: True, log=lambda m: None)
                r1 = CC.enviar_latido(url, tok, True, {})
                c.guardar_correo(correo(64512, "64192718"), "2026-11-17T10:03:00", {"id": "64512"})
                r2 = CC.enviar_latido(url, tok, True, {})
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertTrue(r1["correo_central"])
        with mock.patch.dict(os.environ, {"HAC_ZAC_DATOS": dir_p}):
            self.assertEqual(CC.aplicar_respuesta(r1), ["64512"])
            s = cola.solicitudes()[0]
            self.assertFalse(s["plantilla"], "sin correo todavia")
            CC.aplicar_respuesta(r2)
            s = cola.solicitudes()[0]
            self.assertTrue(s["plantilla"])
            self.assertEqual(s["origen"], "central")
            self.assertIn("ZTEGC000064512", s["datos"]["txt_sol"])
            self.assertEqual(cola.siguiente_para_script("Ana Uno")["id"], "64512", "lista para Procesar")
            self.assertEqual(CC.plantillas_listas(), ["64512"])
            CC.aplicar_respuesta(r2)                      # repetir el latido no duplica nada
            self.assertEqual(len(cola.solicitudes()), 1)


if __name__ == "__main__":
    unittest.main()
