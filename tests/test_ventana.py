# -*- coding: utf-8 -*-
"""Pruebas del diseno adaptable: la vista no debe quedar cortada al abrir (sin maximizar y restaurar)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk  # noqa: E402
from hac_zac import adaptable as ad  # noqa: E402


def _tk():
    try:
        r = tk.Tk()
    except tk.TclError:
        return None
    r.report_callback_exception = lambda *a: _tk.errores.append(a[1])
    return r


_tk.errores = []


def esperar(r, ms):
    r.after(ms, r.quit)
    r.mainloop()


class PruebasVentana(unittest.TestCase):
    def setUp(self):
        _tk.errores.clear()
        self.r = _tk()
        if self.r is None:
            self.skipTest("sin pantalla")
        self.r.geometry("400x300")

    def tearDown(self):
        if self.r is not None:
            self.r.destroy()

    def test_contenido_que_llega_despues_activa_el_scroll(self):
        s = ad.Scrollable(self.r, "black")
        s.pack(fill="both", expand=True)
        tk.Label(s.inner, text="corto").pack()
        esperar(self.r, 300)
        self.assertFalse(s._visible)
        for i in range(30):                       # p. ej. la cola o una plantilla que se carga despues
            tk.Label(s.inner, text="fila %d" % i).pack()
        esperar(self.r, ad.VIGILAR_MS * 3)        # sin cambiar el tamano de la ventana
        self.assertTrue(s._visible, "la barra de desplazamiento debe aparecer sola")
        alto = int(str(s.canvas.cget("scrollregion")).split()[-1])
        self.assertGreaterEqual(alto, s.inner.winfo_reqheight())

    def test_barra_en_vista_oculta_se_acomoda_al_mostrarse(self):
        vista = tk.Frame(self.r)                  # vista que no se esta mostrando (otra pestana)
        inner = tk.Frame(vista)
        inner.pack(fill="x")
        f = ad.Flujo(inner, "black")
        f.grid(row=0, column=0, sticky="ew")
        inner.columnconfigure(0, weight=1)
        cs = [tk.Checkbutton(f, text="opcion bastante larga %d" % i) for i in range(5)]
        for c in cs:
            c.pack(side="left")
        esperar(self.r, 200)
        vista.pack(fill="both", expand=True)      # se cambia a esa pestana
        esperar(self.r, 400)
        self.assertEqual(_tk.errores, [])
        self.assertTrue(all(c.winfo_ismapped() for c in cs), "todas las opciones deben verse")
        self.assertEqual(f._modo, "grid")         # no caben en 400 px: se reparten en filas

    def test_flujo_vuelve_a_una_fila_sin_error(self):
        f = ad.Flujo(self.r, "black")
        f.pack(fill="x")
        cs = [tk.Checkbutton(f, text="opcion bastante larga %d" % i) for i in range(4)]
        for c in cs:
            c.pack(side="left")
        esperar(self.r, 300)
        self.assertEqual(f._modo, "grid")
        self.r.geometry("1900x300")
        esperar(self.r, 400)
        self.assertEqual(_tk.errores, [])
        self.assertEqual(f._modo, "pack")
        self.assertTrue(all(c.winfo_manager() == "pack" for c in cs))


if __name__ == "__main__":
    unittest.main()
