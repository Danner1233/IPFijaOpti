# -*- coding: utf-8 -*-
"""Ritmo del reparto (descanso segun libres), buscador de IPs por nodo (Excel sin openpyxl) y guia de emergencia."""
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("HAC_ZAC_DATOS", tempfile.mkdtemp(prefix="hz_rb_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hac_zac import buscador_ips as B, reparto_equipo as R  # noqa: E402

AHORA = datetime(2026, 11, 19, 10, 0, 0)
ROSTER = [{"nombre": "Ana", "activo": True, "ultimo": "2026-11-19T08:00:00"},
          {"nombre": "Beto", "activo": True, "ultimo": "2026-11-19T09:00:00"}]
PRES = {"ana": "en_linea", "beto": "en_linea"}


def utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def libre(i):
    return {"ID": i, "Created": utc(AHORA - timedelta(minutes=30 - i)), "PEM_ASIGNADO": "", "Est_Seg": "Sin Asignar",
            "ActivApoyo": "No", "Observaciones": ""}


def cerrada(pem, hace_s):
    return {"ID": 900, "Created": utc(AHORA - timedelta(minutes=20)), "Modified": utc(AHORA - timedelta(seconds=hace_s)),
            "PEM_ASIGNADO": pem, "Est_Seg": "Exitosa", "ActivApoyo": "No", "Observaciones": ""}


class PruebasRitmo(unittest.TestCase):
    def test_tabla(self):
        self.assertEqual([R.descanso_s(n) for n in (1, 3, 4, 5, 9)], [15, 15, 8, 0, 0])

    def test_pocas_libres_descansa_15_s(self):
        items = [libre(1), libre(2), cerrada("Ana", 5)]
        self.assertEqual(R.en_descanso(items, ROSTER, AHORA), {"Ana": 10})
        self.assertEqual([n for _, n in R.plan(items, ROSTER, PRES, AHORA)], ["Beto"], "Ana descansa")
        self.assertEqual(sorted(n for _, n in R.plan(items, ROSTER, PRES, AHORA + timedelta(seconds=11))),
                         ["Ana", "Beto"], "paso el descanso")

    def test_muchas_libres_sin_descanso(self):
        items = [libre(i) for i in range(1, 6)] + [cerrada("Ana", 2)]
        self.assertEqual(R.en_descanso(items, ROSTER, AHORA), {})
        self.assertEqual(sorted(n for _, n in R.plan(items, ROSTER, PRES, AHORA)), ["Ana", "Beto"])

    def test_cierre_viejo_no_cuenta(self):
        self.assertEqual(R.en_descanso([libre(1), cerrada("Ana", 120)], ROSTER, AHORA), {})


# ---------------------------------------------------------------------------------------------- Excel de prueba
def _xlsx(ruta, filas):
    """xlsx minimo (cadenas compartidas + una hoja) como lo genera Excel."""
    comp, idx = [], {}

    def s(v):
        if v not in idx:
            idx[v] = len(comp)
            comp.append(v)
        return idx[v]

    def col(i):
        out = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            out = chr(65 + r) + out
        return out

    xml_filas = []
    for r, fila in enumerate(filas, 1):
        celdas = []
        for c, v in enumerate(fila):
            if v is None:
                continue
            ref = "%s%d" % (col(c), r)
            if isinstance(v, (int, float)):
                celdas.append('<c r="%s"><v>%s</v></c>' % (ref, v))
            else:
                celdas.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, s(v)))
        xml_filas.append('<row r="%d">%s</row>' % (r, "".join(celdas)))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    nsr = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook %s %s><sheets><sheet name="query" sheetId="1" r:id="rId1"/>'
                                      '</sheets></workbook>' % (ns, nsr))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", "<sst %s>%s</sst>" % (ns, "".join("<si><t>%s</t></si>" % v for v in comp)))
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet %s><sheetData>%s</sheetData></worksheet>"
                   % (ns, "".join(xml_filas)))


CAB = ["Cuenta_RR", "Creado", "Regional", "Tipo Reporte Resultado Actividad", "IP Asignada", "Puerta Enlace",
       "ID CASO:NOMBRE_CLIENTE", "PROPIEDA_RED", "OLT_ATP", "UVLAN", "ID CASO:NODO_FINAL"]


class PruebasBuscador(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hz_rb_x_")
        self.xlsx = os.path.join(self.d, "Buscador.xlsx")
        _xlsx(self.xlsx, [CAB,
                          ["1", 46000.5, "CENTRO", "Exitosa", "190.143.35.183", "190.143.35.129", "CLIENTE A",
                           "Red ATP", "OLT1", "201", "XQ099F"],
                          ["2", 46010.2, "CENTRO", "Exitosa", "190.143.35.140", "190.143.35.129", "CLIENTE B",
                           "Red ATP", "OLT1", "201", "xq099f"],
                          ["3", 46005, "CENTRO", "Exitosa", "10.0.0.9", "10.0.0.1", "CLIENTE C", "Claro", "", "",
                           "XQ099F"],
                          ["4", 46011, "CENTRO", "No Exitosa", "1.1.1.1", "1.1.1.254", "CLIENTE D", "", "", "",
                           "XQ099F"],
                          ["5", 46011, "CENTRO", "Exitosa", "", "", "CLIENTE E", "", "", "", "XQ099F"],
                          ["6", 46012, "SUR", "Exitosa", "172.16.0.5", "172.16.0.1", "CLIENTE F", "", "", "",
                           "AB100"]])
        self.eq = tempfile.mkdtemp(prefix="hz_rb_e_")

    def test_importar_y_buscar(self):
        ind = B.importar(self.xlsx, self.eq)
        self.assertEqual((ind["filas"], ind["exitosas"]), (6, 4))
        r = B.buscar(B.cargar(self.eq), "xq099f")
        self.assertEqual([(x["nodo"], x["gw"], x["n"]) for x in r],
                         [("XQ099F", "190.143.35.129", 2), ("XQ099F", "10.0.0.1", 1)], "la mas usada primero")
        self.assertEqual(r[0]["ips"], ["190.143.35.140", "190.143.35.183"], "IPs ya usadas, ordenadas")
        self.assertEqual(r[0]["red"], "Red ATP")
        self.assertTrue(r[0]["ultima"].startswith("2025-"))
        self.assertEqual(B.buscar(ind, "zz"), [])
        self.assertEqual([x["nodo"] for x in B.buscar(ind, "AB")], ["AB100"], "por comienzo")

    def test_no_guarda_datos_de_clientes(self):
        B.importar(self.xlsx, self.eq)
        with open(B.ruta_indice(self.eq), encoding="utf-8") as f:
            texto = f.read()
        self.assertNotIn("CLIENTE", texto)
        self.assertNotIn('"1"', texto, "ni la cuenta RR")

    def test_excel_sin_columnas(self):
        _xlsx(self.xlsx, [["A", "B"], ["1", "2"]])
        with self.assertRaises(B.ErrorExcel):
            B.importar(self.xlsx, self.eq)

    def test_no_es_excel(self):
        with open(self.xlsx, "w") as f:
            f.write("hola")
        with self.assertRaises(B.ErrorExcel):
            B.importar(self.xlsx, self.eq)


class PruebasGuia(unittest.TestCase):
    def test_comandos_iguales_al_script(self):
        from hac_zac import panel_emergencia
        texto = panel_emergencia.texto_guia()
        script = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "SCRIPT_HAC_ZAC_UNIFICADO.py"), encoding="utf-8").read()
        for cmd in ("sho bgp vpnv4 unicast rd 100:15604", "display ip routing-table vpn-instance",
                    "dis arp int", "display ont info by-sn", "display traffic table ip from-index 0 | no-more",
                    "security max-mac-learn 5", "vlan port eth_0/4 mode hybrid def-vlan 201", "PROVISION_NACIONAL_HPE"):
            self.assertIn(cmd, texto)
            self.assertIn(cmd, script, "el comando de la guia debe ser el mismo que usa el script")


if __name__ == "__main__":
    unittest.main()
