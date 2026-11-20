# -*- coding: utf-8 -*-
"""Copias en conflicto de OneDrive en presencia (el PEM salia dos veces) y conteo de la cola en SharePoint."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_cp_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import cola, presencia, reparto_equipo as R  # noqa: E402


def escribir(c, archivo, **d):
    os.makedirs(presencia.carpeta(c), exist_ok=True)
    with open(os.path.join(presencia.carpeta(c), archivo), "w", encoding="utf-8") as f:
        json.dump(d, f)


class PruebasCopiasEnConflicto(unittest.TestCase):
    def setUp(self):
        self.c = tempfile.mkdtemp()
        self.ahora = datetime.now()
        viejo = (self.ahora - timedelta(hours=1)).isoformat(timespec="seconds")
        # como en el PC de Danner: la copia de OneDrive quedo de las 11:07, la buena se actualiza cada minuto
        escribir(self.c, "Juan Gutierrez-DESKTOP-42U3OEG.json", nombre="Juan Gutierrez", estado="en_linea",
                 actualizado=viejo, ultima_actividad=viejo)
        escribir(self.c, "Juan Gutierrez.json", nombre="Juan Gutierrez", estado="en_linea", caso="65264",
                 actualizado=self.ahora.isoformat(timespec="seconds"),
                 ultima_actividad=self.ahora.isoformat(timespec="seconds"))

    def test_sale_una_sola_vez_y_con_el_dato_nuevo(self):
        filas = [f for f in presencia.equipo(self.c, self.ahora) if f["nombre"] == "Juan Gutierrez"]
        self.assertEqual(len(filas), 1)
        self.assertEqual((filas[0]["estado"], filas[0]["caso"]), ("en_linea", "65264"))

    def test_el_reparto_no_lo_cree_desconectado(self):
        self.assertEqual(R.presencia_por_nombre(self.c, self.ahora), {"juan gutierrez": "en_linea"})

    def test_al_publicar_borra_sus_copias(self):
        escribir(self.c, "Juan Gutierrez (1).json", nombre="Juan Gutierrez", estado="ausente", actualizado="")
        escribir(self.c, "Juan Gutierrez Perez.json", nombre="Juan Gutierrez Perez", estado="en_linea",
                 actualizado="")
        presencia.publicar(self.c, "Juan Gutierrez", self.ahora, False, self.ahora)
        self.assertEqual(sorted(os.listdir(presencia.carpeta(self.c))),
                         ["Juan Gutierrez Perez.json", "Juan Gutierrez.json"], "no toca a otra persona")


def item(i, pem="", est="Sin Asignar", hace_min=10):
    creada = (datetime.now() - timedelta(minutes=hace_min)).astimezone(timezone.utc)
    return {"ID": i, "Created": creada.strftime("%Y-%m-%dT%H:%M:%SZ"), "PEM_ASIGNADO": pem, "Est_Seg": est,
            "ActivApoyo": "No", "Observaciones": ""}


class PruebasConteo(unittest.TestCase):
    def test_cuantas_hay(self):
        items = [item(1, hace_min=12), item(2, hace_min=3), item(3, "Ana", "Asignada"), item(4, "Beto", "Exitosa")]
        cola.guardar_conteo(items)
        c = cola.conteo()
        self.assertEqual((c["libres"], c["en_proceso"]), (2, 1))
        t = cola.texto_conteo(c)
        self.assertTrue(t.startswith("2 en cola sin asignar (la más vieja hace 12 min) · 1 en proceso"), t)

    def test_cola_vacia(self):
        cola.guardar_conteo([item(3, "Ana", "Asignada")])
        self.assertTrue(cola.texto_conteo(cola.conteo()).startswith("Cola vacía"))

    def test_dato_viejo_no_se_muestra(self):
        cola.guardar_conteo([item(1)], datetime.now() - timedelta(minutes=5))
        self.assertIsNone(cola.conteo())
        self.assertIn("sin dato", cola.texto_conteo(None))


if __name__ == "__main__":
    unittest.main()
