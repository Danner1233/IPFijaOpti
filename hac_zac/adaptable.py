# -*- coding: utf-8 -*-
"""Piezas para que la interfaz se adapte a cualquier pantalla, resolucion, zoom de Windows (DPI) y tamano de ventana."""
import tkinter as tk
from tkinter import ttk

ESC = 1.0          # factor de escala de la pantalla (1.0 = 96 dpi, 1.5 = 150 %, ...)
VIGILAR_MS = 250   # cada cuanto el area con desplazamiento revisa si su contenido cambio de alto


def iniciar(root, forzar=0.0):
    """Calcula el factor de escala. 'forzar' (o la variable HAC_ZAC_ESCALA) fija uno a mano."""
    global ESC
    if forzar:
        root.tk.call("tk", "scaling", forzar * 96 / 72)
    try:
        ESC = max(0.75, min(3.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        ESC = 1.0
    return ESC


def px(n):
    return max(1, int(round(n * ESC)))


def tamano_ventana(root, ancho=1100, alto=800):
    """Tamano inicial: el preferido, pero nunca mayor que ~94 % del ancho y 90 % del alto de la pantalla."""
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(px(ancho), int(sw * 0.94)), min(px(alto), int(sh * 0.90))
    x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2 - px(20))
    return w, h, x, y


class Scrollable(tk.Frame):
    """Contenedor que se estira con la ventana y solo muestra barra de desplazamiento si el contenido no cabe."""

    def __init__(self, padre, bg):
        super().__init__(padre, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._visible = False
        self._req = None
        self.canvas.bind("<Configure>", self._ajustar)
        self.inner.bind("<Configure>", self._ajustar)
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(ev, self._rueda, add="+")
        self._tarea = self.after(VIGILAR_MS, self._vigilar)
        self.bind("<Destroy>", self._al_destruir, add="+")

    def _al_destruir(self, e=None):
        if e is not None and e.widget is not self:
            return
        try:
            self.after_cancel(self._tarea)
        except Exception:
            pass

    def _vigilar(self):
        """El marco interno tiene el alto fijado por el canvas: si su contenido crece o se achica (llega la cola,
        se carga una plantilla, se cambia de vista) Tk NO avisa con <Configure>, y la vista quedaba cortada hasta
        maximizar y restaurar. Se revisa el alto pedido y se reajusta solo cuando cambia."""
        try:
            if not self.winfo_exists():
                return
            if self.inner.winfo_reqheight() != self._req:
                self._ajustar()
        except tk.TclError:
            return
        self._tarea = self.after(VIGILAR_MS, self._vigilar)

    def _ajustar(self, e=None):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        req = self.inner.winfo_reqheight()
        self._req = req
        alto = max(h, req)
        self.canvas.itemconfigure(self.win, width=w, height=alto)
        self.canvas.configure(scrollregion=(0, 0, w, alto))
        # histeresis para que la barra no parpadee
        if not self._visible and req > h + 2:
            self.vsb.pack(side="right", fill="y")
            self._visible = True
        elif self._visible and req < h - px(40):
            self.vsb.pack_forget()
            self._visible = False
            self.canvas.yview_moveto(0)

    def _rueda(self, e):
        if not self._visible:
            return
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None:                      # Text/Treeview/Listbox se desplazan solos
            if w.winfo_class() in ("Text", "Treeview", "Listbox", "TCombobox", "Toplevel"):
                return
            if w is self:
                break
            w = w.master
        if w is None:
            return
        paso = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
        self.canvas.yview_scroll(paso * 3, "units")


class Flujo(tk.Frame):
    """Barra de botones: en una fila si caben; si no, se reparte en varias filas (sin cortarse)."""

    def __init__(self, padre, bg, hueco=6):
        super().__init__(padre, bg=bg)
        self.hueco = hueco
        self._info = {}
        self._modo = "pack"
        self.bind("<Configure>", lambda e: self._reflujo())
        # Si la barra esta en una vista oculta, se acomoda cuando se muestra (ver _reflujo).
        self.bind("<Map>", lambda e: self.after_idle(self._reflujo) if e.widget is self else None, add="+")

    @staticmethod
    def _pad(v):
        if isinstance(v, (tuple, list)):
            return sum(int(x) for x in v)
        return 2 * int(v or 0)

    def _reflujo(self):
        # Con la barra oculta (p. ej. la Cola mientras se ve Operacion) Tk falla al pasar de pack a grid
        # ("can't determine container window") y dejaba opciones sin mostrar. Se espera al <Map>.
        try:
            if not self.winfo_ismapped():
                return
        except tk.TclError:
            return
        hijos = [h for h in self.winfo_children() if h.winfo_manager() in ("pack", "grid")]
        if not hijos:
            return
        for h in hijos:
            if h.winfo_manager() == "pack":
                try:
                    inf = h.pack_info()
                    inf.pop("in", None)
                    self._info[h] = inf
                except tk.TclError:
                    pass
                if self._modo == "grid":
                    h.pack_forget()
        disp = self.winfo_width()
        total = sum(h.winfo_reqwidth() + self._pad(self._info.get(h, {}).get("padx", 0)) for h in hijos)
        if disp <= 1 or total <= disp:
            if self._modo == "grid" or any(h.winfo_manager() == "grid" for h in hijos):
                # Tk 9 no deja mezclar: primero se sueltan TODOS de grid y despues se empaquetan.
                for h in hijos:
                    if h.winfo_manager() == "grid":
                        h.grid_forget()
                for h in hijos:
                    h.pack(**self._info.get(h, {"side": "left"}))
                self._modo = "pack"
            return
        for h in hijos:
            if h.winfo_manager() == "pack":
                h.pack_forget()
        fila = col = 0
        usado = 0
        for h in hijos:
            ancho = h.winfo_reqwidth() + self.hueco
            if usado and usado + ancho > disp:
                fila, col, usado = fila + 1, 0, 0
            if h.winfo_manager() == "pack":
                h.pack_forget()
            h.grid(row=fila, column=col, padx=(0, self.hueco), pady=(0, self.hueco), sticky="w")
            col += 1
            usado += ancho
        self._modo = "grid"


def envolver(etiqueta, margen=0, minimo=200):
    """El texto de la etiqueta se ajusta al ancho disponible."""
    padre = etiqueta.master

    def aj(e):
        etiqueta.config(wraplength=max(px(minimo), e.width - px(margen)))
    padre.bind("<Configure>", aj, add="+")


def tabla_fluida(tree, anchos, minimo=50):
    """Las columnas reparten el ancho disponible en proporcion a 'anchos'."""
    total = float(sum(anchos)) or 1.0
    cols = list(tree["columns"])

    def aj(e):
        disp = e.width - px(6)
        if disp < 50:
            return
        for c, w in zip(cols, anchos):
            tree.column(c, width=max(px(minimo), int(disp * w / total)), stretch=True)
    tree.bind("<Configure>", aj, add="+")


def dos_columnas(contenedor, izq, der, umbral=900):
    """izq y der lado a lado si caben; si no, una debajo de la otra."""
    estado = {"modo": None}

    def aj(e):
        modo = "lado" if e.width >= px(umbral) else "pila"
        if modo == estado["modo"]:
            return
        estado["modo"] = modo
        izq.pack_forget()
        der.pack_forget()
        if modo == "lado":
            izq.pack(side="left", fill="both", expand=True)
            der.pack(side="left", padx=(14, 0), anchor="n")
        else:
            izq.pack(side="top", fill="x")
            der.pack(side="top", fill="x", pady=(8, 0), anchor="w")
    contenedor.bind("<Configure>", aj, add="+")


def plantilla_y_datos(contenedor, col_t, col_d, minimo_datos=470, al_modo=None):
    """Pantalla ancha: la plantilla (larga y angosta) a la izquierda y los datos a la derecha.
    Pantalla angosta: datos arriba y la plantilla debajo, a todo el ancho."""
    estado = {"modo": None}

    def aj(e=None):
        ancho = contenedor.winfo_width()
        if ancho <= 1:
            return
        # lado a lado solo si caben la plantilla (su ancho real) y un mínimo para los datos
        modo = "lado" if ancho >= col_t.winfo_reqwidth() + px(minimo_datos) + px(14) else "pila"
        if modo == estado["modo"]:
            return
        estado["modo"] = modo
        col_t.pack_forget()
        col_d.pack_forget()
        if modo == "lado":
            col_t.pack(side="left", fill="y", anchor="n")
            col_d.pack(side="left", fill="both", expand=True, padx=(14, 0), anchor="n")
        else:
            col_d.pack(side="top", fill="x")
            col_t.pack(side="top", fill="both", expand=True, pady=(10, 0))
        if al_modo:
            al_modo(modo)
    contenedor.bind("<Configure>", aj, add="+")
    # la plantilla cambia de ancho al cargar otra solicitud: se recalcula aunque la ventana no cambie de tamano
    col_t.bind("<Configure>", lambda e: contenedor.after_idle(aj), add="+")
