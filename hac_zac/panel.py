# -*- coding: utf-8 -*-
import os
import re
"""Paneles de la interfaz: Plantilla (resultado), Historial de solicitudes e IP de Capa 2."""
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import documentacion as doc
from . import adaptable as ad
from . import credenciales
from . import estados
from .registro import URL_CASO_BRIDGE, URL_NETCRACKER, URL_VALIDACION_RED
from .segmentos import segmento_de_ip

C = {}
FONT = "Segoe UI"
SERIF = "Georgia"
BOTON = None   # fabrica de botones de la App: BOTON(padre, texto, cmd, primario, ancho)


def configurar(colores, fuente, fabrica_boton):
    global C, FONT, BOTON
    C, FONT, BOTON = colores, fuente, fabrica_boton
    s = ttk.Style()
    s.configure("HZ.Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["txt"],
                rowheight=ad.px(30), borderwidth=0, font=(FONT, 10), bordercolor=C["card"],
                lightcolor=C["card"], darkcolor=C["card"])
    s.configure("HZ.Treeview.Heading", background=C["card"], foreground=C["mut"], font=(FONT, 9, "bold"),
                borderwidth=0, relief="flat", padding=(6, 6))
    s.map("HZ.Treeview", background=[("selected", C["acc_soft"])], foreground=[("selected", C["txt"])])
    s.map("HZ.Treeview.Heading", background=[("active", C["card2"])])
    s.configure("HZ.TCombobox", fieldbackground=C["card"], background=C["card"], foreground=C["txt"],
                arrowcolor=C["mut"], borderwidth=1, bordercolor=C["line"], lightcolor=C["line"],
                darkcolor=C["line"], padding=4)
    s.map("HZ.TCombobox", fieldbackground=[("readonly", C["card"])], foreground=[("readonly", C["txt"])],
          selectbackground=[("readonly", C["card"])], selectforeground=[("readonly", C["txt"])])


def _tabla(padre, columnas, anchos, alto=8):
    marco = tk.Frame(padre, bg=C["card"], highlightbackground=C["line"], highlightcolor=C["line"], highlightthickness=1)
    t = ttk.Treeview(marco, columns=columnas, show="headings", style="HZ.Treeview", height=min(alto, 5),
                     selectmode="browse")
    for c, w in zip(columnas, anchos):
        t.heading(c, text=c)
        t.column(c, width=ad.px(w), minwidth=ad.px(40), anchor="w")
    ad.tabla_fluida(t, anchos)
    sb = ttk.Scrollbar(marco, command=t.yview)
    t.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(fill="both", expand=True)
    return marco, t


def _ayuda(padre, texto, pady=(0, 8)):
    """Texto de ayuda que se ajusta al ancho disponible."""
    a = tk.Label(padre, text=texto, bg=C["bg"], fg=C["mut"], font=(FONT, 10), justify="left")
    a.pack(anchor="w", pady=pady)
    ad.envolver(a)
    return a


def _entry(padre, **kw):
    return tk.Entry(padre, bg=C["card"], fg=C["txt"], relief="flat", insertbackground=C["txt"],
                    font=(FONT, 11), highlightthickness=1, highlightbackground=C["line"],
                    highlightcolor=C["acc"], **kw)


ESTADOS = estados.OPCIONES_MANUALES


def menu_mas(widget, opciones):
    """Menu desplegable oscuro: opciones = [(texto, funcion)] (None = separador)."""
    m = tk.Menu(widget, tearoff=0, bg=C["card2"], fg=C["txt"], activebackground=C["acc_soft"],
                activeforeground=C["acc"], bd=0, relief="flat", font=(FONT, 10))
    for o in opciones:
        if o is None:
            m.add_separator()
        else:
            m.add_command(label="  %s  " % o[0], command=o[1])
    x = widget.winfo_rootx()
    y = widget.winfo_rooty() + widget.winfo_height()
    try:
        m.tk_popup(x, y)
    finally:
        m.grab_release()
COLOR_RES = {"Exitosa": "ok", "Escalamiento": "warn", "No exitosa": "err"}


def menu_estado(widget, al_elegir):
    """Menu desplegable con los 3 estados; al_elegir(estado)."""
    m = tk.Menu(widget, tearoff=0, bg=C["card"], fg=C["txt"], activebackground=C["acc_soft"],
                activeforeground=C["txt"], bd=0, font=(FONT, 10))
    for e in ESTADOS:
        m.add_command(label=e, command=lambda e=e: al_elegir(e))
    x, y = widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height()
    try:
        m.tk_popup(x, y)
    finally:
        m.grab_release()


# ======================================================================================= IPs LIBRES
class VentanaIPs(tk.Toplevel):
    """Recuadro aparte: segmentos con sus IP libres para seleccionar y copiar."""

    def __init__(self, padre, segmentos, titulo, usar_ip, inicial=0):
        super().__init__(padre)
        self.segs, self.usar_ip = segmentos, usar_ip
        self.title("IP libres  -  " + titulo)
        self.configure(bg=C["bg"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d" % (min(ad.px(660), int(sw * 0.9)), min(ad.px(540), int(sh * 0.85))))
        self.minsize(min(ad.px(480), int(sw * 0.9)), min(ad.px(380), int(sh * 0.85)))
        self.attributes("-topmost", True)
        tk.Label(self, text="IP libres (estado Incomplete en el ARP)", bg=C["bg"], fg=C["txt"],
                 font=(SERIF, 13, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(self, text="Haga clic en un segmento o en una IP y pulse Ctrl + C para copiarlo.",
                 bg=C["bg"], fg=C["mut"], font=(FONT, 10)).pack(anchor="w", padx=16)
        cuerpo = tk.Frame(self, bg=C["bg"])
        cuerpo.pack(fill="both", expand=True, padx=16, pady=10)
        m, self.tseg = _tabla(cuerpo, ("Segmento", "Libres"), (150, 55), alto=8)
        m.pack(side="left", fill="y")
        self.tseg.bind("<<TreeviewSelect>>", lambda e: self._llenar())
        self.tseg.bind("<Control-c>", lambda e: self._copiar_segmento())
        self.tseg.bind("<Control-C>", lambda e: self._copiar_segmento())
        marco = tk.Frame(cuerpo, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        marco.pack(side="left", fill="both", expand=True, padx=(10, 0))
        sb = ttk.Scrollbar(marco)
        sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(marco, bg=C["card"], fg=C["txt"], font=("Consolas", 12), relief="flat",
                             selectbackground=C["acc_soft"], selectforeground=C["txt"], activestyle="none",
                             exportselection=False, yscrollcommand=sb.set)
        self.lb.pack(fill="both", expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind("<Double-1>", lambda e: self._copiar())
        self.lb.bind("<Control-c>", lambda e: self._copiar())
        self.lb.bind("<Control-C>", lambda e: self._copiar())
        self.lbl = tk.Label(self, text="", bg=C["bg"], fg=C["ok"], font=(FONT, 10), anchor="w")
        self.lbl.pack(fill="x", padx=16)
        barra = ad.Flujo(self, C["bg"])
        barra.pack(fill="x", padx=16, pady=(4, 6))
        BOTON(barra, "Copiar segmento", self._copiar_segmento, True, 16).pack(side="left")
        BOTON(barra, "Copiar IP", self._copiar, True, 10).pack(side="left", padx=5)
        BOTON(barra, "Copiar todas", self._copiar_todas, False, 11).pack(side="left")
        barra2 = ad.Flujo(self, C["bg"])
        barra2.pack(fill="x", padx=16, pady=(0, 14))
        BOTON(barra2, "Usar como IP", lambda: self._usar("ip"), False, 14).pack(side="left")
        BOTON(barra2, "Usar como bridge", lambda: self._usar("ip_bridge"), False, 16).pack(side="left", padx=5)
        for s_ in segmentos:
            self.tseg.insert("", "end", values=(s_["red"], s_["n_libres"]))
        k = self.tseg.get_children()
        if k:
            sel = k[min(max(inicial, 0), len(k) - 1)]
            self.tseg.selection_set(sel)
            self.tseg.focus(sel)
        self.tseg.focus_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def _libres(self):
        sel = self.tseg.selection()
        return self.segs[self.tseg.index(sel[0])]["libres"] if sel else []

    def _llenar(self):
        self.lb.delete(0, "end")
        for ip in self._libres():
            self.lb.insert("end", ip)
        if self.lb.size():
            self.lb.selection_set(0)

    def _ip(self):
        sel = self.lb.curselection()
        return self.lb.get(sel[0]) if sel else ""

    def _poner(self, texto, msg):
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.update()
        self.lbl.config(text=msg)

    def _copiar_segmento(self):
        sel = self.tseg.selection()
        if sel:
            red = self.segs[self.tseg.index(sel[0])]["red"]
            self._poner(red, "Segmento copiado: " + red)

    def _copiar(self):
        ip = self._ip()
        if ip:
            self._poner(ip, "Copiada: " + ip)

    def _copiar_todas(self):
        libres = self._libres()
        if libres:
            self._poner("\n".join(libres), "Copiadas %d IP del segmento" % len(libres))

    def _usar(self, destino):
        ip = self._ip()
        if ip:
            self.usar_ip(destino, ip)
            self._poner(ip, "%s: %s (también copiada)" % ("IP asignada" if destino == "ip" else "IP bridge", ip))


# ======================================================================================= PLANTILLA
class PanelPlantilla(tk.Frame):
    def __init__(self, padre, servicio, al_cambiar=None):
        super().__init__(padre, bg=C["bg"])
        self.sv, self.al_cambiar = servicio, al_cambiar
        self.rec = None
        self._guardar_id = None
        self._cargando = False

        cab = tk.Frame(self, bg=C["bg"])
        cab.pack(fill="x", pady=(2, 6))
        self.banner = tk.Label(cab, text="", bg=C["bg"], fg=C["ok"], font=(SERIF, 16, "bold"), anchor="w")
        self.banner.pack(side="left")
        self.pill = tk.Label(cab, text="", bg=C["card2"], fg=C["mut"], font=(FONT, 9, "bold"), padx=8, pady=3,
                             cursor="hand2")
        self.pill.pack(side="right")
        self.pill.bind("<Button-1>", lambda e: self._menu_estado())
        self.pill_doc = tk.Label(cab, text="", bg=C["card2"], fg=C["mut"], font=(FONT, 9, "bold"), padx=8, pady=3)
        self.pill_doc.pack(side="right", padx=6)

        # ======== cuerpo: plantilla (larga y angosta) | datos
        cuerpo = tk.Frame(self, bg=C["bg"])
        cuerpo.pack(fill="both", expand=True, pady=(8, 0))
        col_t = tk.Frame(cuerpo, bg=C["bg"])          # plantilla + acciones
        col_d = tk.Frame(cuerpo, bg=C["bg"])          # tarjetas de datos
        ad.plantilla_y_datos(cuerpo, col_t, col_d, minimo_datos=470, al_modo=self._modo_cuerpo)

        def tarjeta(titulo, relleno=(0, 10)):
            card = tk.Frame(col_d, bg=C["card"], highlightbackground=C["line"], highlightcolor=C["line"],
                            highlightthickness=1)
            card.pack(fill="x", pady=relleno)
            tk.Label(card, text=titulo, bg=C["card"], fg=C["mut"], font=(FONT, 9, "bold")).pack(
                anchor="w", padx=14, pady=(10, 4))
            inner = tk.Frame(card, bg=C["card"])
            inner.pack(fill="x", padx=14, pady=(0, 12))
            return inner

        # ---- 1) la solicitud
        c1 = tarjeta("SOLICITUD", (0, 10))
        self.resumen = tk.Label(c1, text="", bg=C["card"], fg=C["txt"], font=(FONT, 10), anchor="w", justify="left")
        self.resumen.pack(fill="x")
        ad.envolver(self.resumen)

        # ---- 2) equipo: MAC o serial (el que se tenga) y la cuenta RR, para entrar a la ONT
        c2 = tarjeta("PARA ENTRAR A LA ONT")
        self.ent_ont = {}
        self.lbl_ont = {}

        def fila_copiable(clave, nombre, con_sin_puntos=False):
            f = tk.Frame(c2, bg=C["card"])
            f.pack(fill="x", pady=2)
            self.lbl_ont[clave] = tk.Label(f, text=nombre, width=8, anchor="w", bg=C["card"], fg=C["mut"],
                                           font=(FONT, 9, "bold"))
            self.lbl_ont[clave].pack(side="left")
            e = tk.Entry(f, bg=C["card2"], fg=C["txt"], relief="flat", font=("Consolas", 12, "bold"),
                         readonlybackground=C["card2"], insertbackground=C["txt"], highlightthickness=0, bd=0)
            e.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
            e.config(state="readonly")
            BOTON(f, "Copiar", lambda k=clave: self._copiar_ont(k, False), True, 8).pack(side="left")
            if con_sin_puntos:
                self.b_sin_puntos = BOTON(f, "Sin :", lambda k=clave: self._copiar_ont(k, True), False, 6)
                self.b_sin_puntos.pack(side="left", padx=(4, 0))
            self.ent_ont[clave] = e

        fila_copiable("equipo", "MAC", True)
        fila_copiable("rr", "Cuenta RR")

        # ---- 3) segmentos
        c3 = tarjeta("SEGMENTOS  ·  doble clic: ver IP libres  ·  clic + Ctrl+C: copiar")
        m, self.tabla = _tabla(c3, ("Red", "Máscara", "Gateway", "Libres"), (150, 120, 120, 56), alto=4)
        m.pack(fill="x")
        self.tabla.bind("<<TreeviewSelect>>", lambda e: self._seleccion())
        self.tabla.bind("<Double-1>", lambda e: self.after(10, self.abrir_ips))          # doble clic: ver sus IP libres
        self.tabla.bind("<Control-c>", lambda e: self._copiar_segmento_tabla())
        self.tabla.bind("<Control-C>", lambda e: self._copiar_segmento_tabla())

        # ---- 4) direccionamiento
        c4 = tarjeta("DIRECCIONAMIENTO")
        c4.columnconfigure(0, weight=1)
        c4.columnconfigure(1, weight=1)
        tk.Label(c4, text="IP asignada", bg=C["card"], fg=C["mut"], font=(FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(c4, text="IP bridge", bg=C["card"], fg=C["mut"], font=(FONT, 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.cb_ip = ttk.Combobox(c4, width=16, style="HZ.TCombobox")
        self.cb_ipb = ttk.Combobox(c4, width=16, style="HZ.TCombobox")
        self.cb_ip.grid(row=1, column=0, sticky="ew", ipady=4)
        self.cb_ipb.grid(row=1, column=1, sticky="ew", padx=(8, 0), ipady=4)
        for cb in (self.cb_ip, self.cb_ipb):
            cb.bind("<<ComboboxSelected>>", lambda e: self._ips())
            cb.bind("<FocusOut>", lambda e: self._ips())
            cb.bind("<Return>", lambda e: self._ips())
        self.lbl_mg = tk.Label(c4, text="", bg=C["card"], fg=C["mut"], font=(FONT, 9), justify="left", anchor="w")
        self.lbl_mg.grid(row=2, column=0, sticky="w", pady=(6, 0))
        BOTON(c4, "IPs libres…", self.abrir_ips, False, 12).grid(row=2, column=1, sticky="e", pady=(6, 0))
        self.ventana_ips = None

        # ---- 5) ping
        c5 = tarjeta("PING (opcional)", (0, 0))
        self.t_ping = tk.Text(c5, width=30, height=3, bg=C["card2"], fg=C["txt"], relief="flat",
                              font=("Consolas", 9), insertbackground=C["txt"])
        self.t_ping.pack(fill="x")
        self.t_ping.bind("<KeyRelease>", lambda e: self._ping())

        # ---- plantilla (columna izquierda: larga y angosta)
        marco = tk.Frame(col_t, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        sb = ttk.Scrollbar(marco)
        self.t = tk.Text(marco, bg=C["card"], fg=C["txt"], relief="flat", font=("Consolas", 10), wrap="word",
                         width=50, height=30, padx=12, pady=8, yscrollcommand=sb.set, undo=True,
                         insertbackground=C["txt"])
        sb.config(command=self.t.yview)
        barra = ad.Flujo(col_t, C["bg"])
        barra.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl_est = tk.Label(col_t, text="", bg=C["bg"], fg=C["mut"], font=(FONT, 9), anchor="w", justify="left")
        self.lbl_est.pack(side="bottom", fill="x")
        ad.envolver(self.lbl_est)
        marco.pack(fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.t.pack(fill="both", expand=True)
        self.t.bind("<<Modified>>", self._modificado)

        BOTON(barra, "Copiar solicitud", self._copiar, True, 16).pack(side="left")
        BOTON(barra, "Copiar direccionamiento final", self._copiar_direccionamiento, True, 26).pack(side="left", padx=5)
        BOTON(barra, "Guardar .txt", self._guardar, False, 12).pack(side="left")
        self.b_mas = BOTON(barra, "Más ▾", lambda: menu_mas(self.b_mas, [
            ("Guardar con otro nombre…", self._con_nombre), ("Regenerar plantilla", self._regenerar), None,
            ("Abrir en Netcracker", self._netcracker), ("Caso bridge", self._caso)]), False, 8)
        self.b_mas.pack(side="left", padx=5)
        BOTON(barra, "Documentar", self._documentar, True, 12).pack(side="left")

    # ---------------------------------------------------------------- cargar
    def cargar(self, rec):
        self._cargando = True
        self.rec = rec
        op = rec.get("operacion") or {}
        res = estados.normalizar(rec.get("resultado") or "")
        color = C[COLOR_RES.get(res, "mut")]
        self.banner.config(text="Solicitud %s" % (rec.get("id") or rec.get("rr") or ""), fg=C["txt"])
        self.pill.config(text="  %s  ▾  " % (res or "Sin estado"), fg=color)
        self._pill_doc()
        e = op.get("entrada") or {}
        capa2 = ("%s (%s)  %s" % (op.get("capa2_nombre"), op.get("capa2_tipo"), op.get("capa2_ip"))
                 if op.get("capa2_nombre") else "")
        pares = (("Cliente", rec.get("cliente")), ("RR", rec.get("rr")), ("Red", rec.get("red")), ("Capa 2", capa2),
                 ("Velocidad", ("%sM" % e.get("velocidad")) if e.get("velocidad") else ""),
                 ("Bridge", "Sí" if e.get("bridge") else "No"))
        self.resumen.config(text="  ·  ".join("%s: %s" % (k, v or "—") for k, v in pares))
        try:
            from . import plantilla as _pl
            sol = _pl.parsear_solicitud(rec.get("txt_sol", "")) if rec.get("txt_sol") else {}
        except Exception:
            sol = {}
        self._poner_ont(rec.get("serial") or sol.get("serial_ont", ""), rec.get("mac") or sol.get("mac_ont", ""),
                        rec.get("rr") or sol.get("rr", ""))
        for i in self.tabla.get_children():
            self.tabla.delete(i)
        for s in op.get("segmentos") or []:
            self.tabla.insert("", "end", values=(s["red"], s["mascara"], s["gateway"], s["n_libres"]))
        kids = self.tabla.get_children()
        if kids:
            self.tabla.selection_set(kids[0])
        self._seleccion(conservar=True)
        self.cb_ip.set(rec.get("ip", ""))
        self.cb_ipb.set(rec.get("ip_bridge", ""))
        self.t_ping.delete("1.0", "end")
        self.t_ping.insert("1.0", rec.get("txt_ping", ""))
        self.t.edit_modified(False)
        self.t.delete("1.0", "end")
        self.t.insert("1.0", rec.get("preview", ""))
        self.t.edit_modified(False)
        self._mg()
        red = rec.get("red")
        self.lbl_est.config(text=("Red %s: valide en %s antes de marcar IPs." % (red, URL_VALIDACION_RED[red]))
                            if red in URL_VALIDACION_RED else
                            ("Archivo: %s" % rec["archivo"] if rec.get("archivo") else
                             "Elija la IP asignada (y la IP bridge si aplica); la plantilla se actualiza sola."))
        self._cargando = False

    def abrir_ips(self):
        """Abre el recuadro de IP libres (o lo trae al frente si ya está abierto)."""
        segs = self._segs()
        if not segs:
            messagebox.showinfo("IP libres", "Esta solicitud no tiene segmentos ni IP libres consultadas.")
            return
        if self.ventana_ips is not None and self.ventana_ips.winfo_exists():
            self.ventana_ips.destroy()
        titulo = (self.rec or {}).get("rr", "")

        def usar(destino, ip):
            (self.cb_ip if destino == "ip" else self.cb_ipb).set(ip)
            self._ips()

        sel = self.tabla.selection()
        ini = self.tabla.index(sel[0]) if sel else 0
        self.ventana_ips = VentanaIPs(self, segs, titulo, usar, ini)

    def _copiar_segmento_tabla(self):
        sel = self.tabla.selection()
        segs = self._segs()
        if sel and segs:
            red = segs[self.tabla.index(sel[0])]["red"]
            self.clipboard_clear()
            self.clipboard_append(red)
            self.update()
            self.lbl_est.config(text="Segmento copiado: " + red)

    def resaltar_segmentos(self):
        """Tras terminar el proceso: sin ventana emergente; deja el primer segmento seleccionado."""
        k = self.tabla.get_children()
        if k:
            self.tabla.selection_set(k[0])
            self.tabla.focus(k[0])
        self.lbl_est.config(text="Doble clic en un segmento para ver sus IP libres; Ctrl+C copia el segmento.")

    def _menu_estado(self):
        """Cambia a mano el estado: Exitosa / Escalamiento / No exitosa."""
        if not (self.rec and self.rec.get("key")):
            return

        def poner(estado):
            rec = self.sv.cambiar_resultado(self.rec["key"], estado)
            if rec:
                self.rec = rec
                self.pill.config(text="  %s  ▾  " % estado, fg=C[COLOR_RES.get(estado, "mut")])
                if self.al_cambiar:
                    self.al_cambiar()

        menu_estado(self.pill, poner)

    def _pill_doc(self):
        r = self.rec or {}
        try:
            d = doc.parse(r.get("preview", ""))
            hoy = doc.documentada_hoy(d)
        except Exception:
            hoy = False
        if r.get("documentada_en") or hoy:
            self.pill_doc.config(text="  ✓ DOCUMENTADA  ", fg=C["ok"])
        else:
            self.pill_doc.config(text="  ○ Pendiente de documentar  ", fg=C["warn"])

    # ---------------------------------------------------------------- red / IP
    def _segs(self):
        return ((self.rec or {}).get("operacion") or {}).get("segmentos") or []

    def _seleccion(self, conservar=False):
        sel = self.tabla.selection()
        segs = self._segs()
        if not sel or not segs:
            self.cb_ip["values"] = self.cb_ipb["values"] = ()
            return
        i = self.tabla.index(sel[0])
        libres = segs[i]["libres"]
        self.cb_ip["values"] = libres
        self.cb_ipb["values"] = libres

    def _mg(self):
        ip = self.cb_ip.get().strip() or self.cb_ipb.get().strip()
        s = segmento_de_ip(self._segs(), ip)
        self.lbl_mg.config(text="%s / %s" % (s["mascara"], s["gateway"]) if s else
                           ("— (la IP no está en un segmento de la interfaz)" if ip else ""))

    def _ips(self):
        if self._cargando or not self.rec:
            return
        ip, ipb = self.cb_ip.get().strip(), self.cb_ipb.get().strip()
        if ip == self.rec.get("ip", "") and ipb == self.rec.get("ip_bridge", ""):
            return
        self._mg()
        self._recargar(self.sv.actualizar(self.rec["key"], ip=ip, ip_bridge=ipb))

    def _ping(self):
        if self._cargando or not self.rec:
            return
        if self._guardar_id:
            self.after_cancel(self._guardar_id)
        self._guardar_id = self.after(700, lambda: self._recargar(
            self.sv.actualizar(self.rec["key"], txt_ping=self.t_ping.get("1.0", "end").strip("\n"))))

    def _recargar(self, rec):
        if rec:
            self.cargar(rec)
            if self.al_cambiar:
                self.al_cambiar()

    # ---------------------------------------------------------------- edicion manual
    def _modificado(self, _e=None):
        if self._cargando or not self.t.edit_modified():
            return
        self.t.edit_modified(False)
        if not self.rec:
            return
        if self._guardar_id:
            self.after_cancel(self._guardar_id)
        self._guardar_id = self.after(900, self._persistir_texto)

    def _persistir_texto(self):
        if self.rec:
            self.rec = self.sv.guardar_texto(self.rec["key"], self._texto(), True) or self.rec
            self.lbl_est.config(text="Cambios manuales guardados en el historial. «Regenerar» rehace la plantilla.")

    def _texto(self):
        return self.t.get("1.0", "end").rstrip("\n") + "\n"

    # ---------------------------------------------------------------- acciones
    def _regenerar(self):
        if self.rec and messagebox.askyesno("Regenerar", "Se rehace la plantilla con los datos actuales y se pierden "
                                            "las ediciones manuales. ¿Continuar?"):
            self._recargar(self.sv.regenerar(self.rec["key"]))

    def _guardar(self, nombre=""):
        if not self.rec:
            return
        try:
            ruta = self.sv.guardar_txt(self.rec["key"], self._texto(), nombre)
        except Exception as e:
            messagebox.showerror("No se pudo guardar", str(e))
            return
        self._recargar(self.sv.store.cargar(self.rec["key"]))
        self.lbl_est.config(text="Guardado en: %s" % ruta)

    def _con_nombre(self):
        if not self.rec:
            return
        from .plantilla import nombre_estandar
        sug = nombre_estandar(self.rec.get("rr", ""), self.rec.get("cliente", ""))
        n = simpledialog.askstring("Guardar con nombre", "Nombre del archivo (sin .txt):", initialvalue=sug, parent=self)
        if n:
            self._guardar(n)

    def _copiar(self):
        self.clipboard_clear()
        from . import plantilla as _pl
        self.clipboard_append(_pl.extraer_solicitud(self._texto()))
        self.update()
        self.lbl_est.config(text="Solicitud copiada al portapapeles.")

    def _modo_cuerpo(self, modo):
        """Ancha: plantilla alta al lado. Angosta: plantilla más baja debajo de los datos."""
        try:
            self.t.config(height=34 if modo == "lado" else 20)
        except Exception:
            pass

    def _poner_ont(self, serial, mac, rr):
        """Muestra UN solo dato del equipo (MAC si se tiene; si no, el serial) y la cuenta RR."""
        if mac:
            nombre, valor = "MAC", mac
        elif serial:
            nombre, valor = "Serial", serial
        else:
            nombre, valor = "Serial / MAC", ""
        self._ont_valores = {"equipo": valor, "rr": rr or ""}
        self.lbl_ont["equipo"].config(text=nombre)
        self.lbl_ont["rr"].config(text="Cuenta RR")
        for k, e in self.ent_ont.items():
            e.config(state="normal")
            e.delete(0, "end")
            e.insert(0, self._ont_valores[k] or "—")
            e.config(state="readonly")
        # «Sin :» solo tiene sentido para una MAC
        if nombre == "MAC":
            self.b_sin_puntos.pack(side="left", padx=(4, 0))
        else:
            self.b_sin_puntos.pack_forget()

    def _copiar_ont(self, clave, sin_puntos=False):
        v = (getattr(self, "_ont_valores", {}) or {}).get(clave, "")
        if not v:
            self.lbl_est.config(text="No hay %s para copiar." % ("la cuenta RR" if clave == "rr" else "MAC ni serial"))
            return
        if sin_puntos:
            v = re.sub(r"[^0-9A-Za-z]", "", v)
        self.clipboard_clear()
        self.clipboard_append(v)
        self.update()
        self.lbl_est.config(text="Copiado: %s" % v)

    def _copiar_direccionamiento(self):
        if not self.rec:
            return
        d = self.sv.datos_plantilla(self.rec)
        if not d.ip:
            messagebox.showinfo("Direccionamiento final", "Elija primero la IP asignada (y la IP bridge si aplica).")
            return
        from .plantilla import construir_direccionamiento
        self.clipboard_clear()
        self.clipboard_append(construir_direccionamiento(d))
        self.update()
        self.lbl_est.config(text="Direccionamiento final copiado (%s)." % ("con bridge" if d.ip_bridge else "sin bridge"))

    def _netcracker(self):
        sel = self.tabla.selection()
        segs = self._segs()
        if sel and segs:
            self.clipboard_clear()
            self.clipboard_append(segs[self.tabla.index(sel[0])]["red"])
        webbrowser.open(URL_NETCRACKER)
        self.lbl_est.config(text="Netcracker abierto. Segmento copiado al portapapeles.")

    def _caso(self):
        caso = URL_CASO_BRIDGE.get((self.rec or {}).get("red"))
        if not caso:
            messagebox.showinfo("Caso bridge", "Solo aplica a redes ONNET (TCO) y ATP (INCLA).")
            return
        webbrowser.open(caso[1])
        n = simpledialog.askstring("Número de caso", "Número del %s generado:" % caso[0], parent=self)
        if n and self.rec.get("archivo"):
            from .plantilla import agregar_caso
            agregar_caso(self.rec["archivo"], n)
            self.lbl_est.config(text="Caso %s agregado al .txt" % n.strip())

    def _documentar(self):
        if not self.rec:
            return
        texto = self._texto()
        d, faltan, hoy = self.sv.revisar_documentacion(texto)
        if faltan:
            messagebox.showwarning("Faltan datos para documentar", "Faltan: %s.\n\nComplete la plantilla (ID de "
                                   "solicitud, regional, actividad, IP asignada…) y vuelva a pulsar Documentar." %
                                   ", ".join(doc.ETIQUETAS.get(k, k) for k in faltan))
            return
        det = "\n".join("%s: %s" % kv for kv in doc.resumen(d))
        sp = self.sv.estado_sp_de(self.sv.store.cargar(self.rec["key"]) or self.rec)
        if sp:
            det += "\n\nAl enviar, en SharePoint la solicitud %s quedará como «%s»." % sp
        if not messagebox.askokcancel("Documentar en Microsoft Forms",
                                      ("⚠ Esta cuenta ya se documentó hoy.\n\n" if hoy else "") + det):
            return
        key = self.rec["key"]
        evento, respuesta = threading.Event(), {"ok": False}

        def confirmar():
            def preguntar():
                respuesta["ok"] = messagebox.askyesno("Enviar formulario", "El formulario está diligenciado.\n"
                                                      "Revíselo en el navegador y confirme: ¿enviarlo ahora?")
                evento.set()
            self.after(0, preguntar)
            evento.wait()
            return respuesta["ok"]

        def avisar_enviado():
            """Tras el Sí: avisa y, al aceptar, deja que el bot cierre la pantalla de Forms."""
            evento2 = threading.Event()

            def alerta():
                messagebox.showinfo("Documentación enviada", "Documentación enviada.\n\n"
                                    "Confirme la pantalla de Forms y pulse Aceptar: se cerrará la pantalla de documentación.")
                evento2.set()
            self.after(0, alerta)
            evento2.wait()

        def trabajo():
            try:
                r = self.sv.documentar(key, texto, confirmar, lambda t: self.after(0, self.lbl_est.config, {"text": t}), avisar_enviado)
                msg = "Documentada." if r == "enviado" else "Envío cancelado."
            except Exception as e:
                msg = "No se pudo documentar: %s" % e
            def final():
                self._recargar(self.sv.store.cargar(key))
                self.lbl_est.config(text=msg)
                if not msg.startswith("Documentada"):          # si se envió, ya se avisó antes
                    messagebox.showinfo("Documentación", msg)
            self.after(0, final)
        threading.Thread(target=trabajo, daemon=True).start()


# ======================================================================================= HISTORIAL
class PanelHistorial(tk.Frame):
    COLS = ("Solicitud", "Cuenta RR", "Cliente", "Red", "Capa 2", "Estado", "Avance",
            "Documentación", "Actualizada")
    FILTROS_ESTADO = ("Todos los estados",) + tuple(ESTADOS)
    FILTROS = ("Todas", "No documentadas", "Documentadas")

    def __init__(self, padre, servicio, abrir):
        super().__init__(padre, bg=C["bg"])
        self.sv, self.abrir = servicio, abrir
        self.regs = []
        tk.Label(self, text="Historial de solicitudes", bg=C["bg"], fg=C["txt"], font=(SERIF, 17, "bold")).pack(anchor="w")
        _ayuda(self, "Cada operación queda guardada con la plantilla, las IP elegidas y el resultado. "
               "Doble clic para reabrirla tal como la dejó. Nunca se guardan contraseñas.")
        f = tk.Frame(self, bg=C["bg"])
        f.pack(fill="x")
        self.q = _entry(f)
        self.q.pack(side="left", fill="x", expand=True, ipady=5)
        self.q.bind("<KeyRelease>", lambda e: self.refrescar())
        self.cb_f = ttk.Combobox(f, values=self.FILTROS, state="readonly", width=16, style="HZ.TCombobox")
        self.cb_f.set(self.FILTROS[0])
        self.cb_f.pack(side="left", padx=(8, 0), ipady=4)
        self.cb_f.bind("<<ComboboxSelected>>", lambda e: self.refrescar())
        self.cb_e = ttk.Combobox(f, values=self.FILTROS_ESTADO, state="readonly", width=17, style="HZ.TCombobox")
        self.cb_e.set(self.FILTROS_ESTADO[0])
        self.cb_e.pack(side="left", padx=(8, 0), ipady=4)
        self.cb_e.bind("<<ComboboxSelected>>", lambda e: self.refrescar())
        b2 = ad.Flujo(self, C["bg"])
        b2.pack(fill="x", pady=(8, 0))
        BOTON(b2, "Abrir", self._abrir, False, 9).pack(side="left")
        BOTON(b2, "Abrir y documentar", self._abrir_documentar, True, 18).pack(side="left", padx=5)
        self.b_estado = BOTON(b2, "Más ▾", lambda: menu_mas(self.b_estado, [
            ("Marcar documentada / pendiente", self._alternar), ("Cambiar estado…", self._menu_estado),
            ("Ver IPs libres", self._ips_libres), None, ("Eliminar", self._eliminar)]), False, 8)
        self.b_estado.pack(side="left")
        m, self.t = _tabla(self, self.COLS, (70, 85, 160, 62, 110, 100, 120, 140, 100), alto=14)
        m.pack(fill="both", expand=True, pady=8)
        self.t.tag_configure("doc", foreground=C["mut"])
        self.t.tag_configure("pend", foreground=C["txt"])
        self.t.bind("<Double-1>", lambda e: self._abrir())
        self.lbl = tk.Label(self, text="", bg=C["bg"], fg=C["mut"], font=(FONT, 9), anchor="w")
        self.lbl.pack(fill="x")
        self.refrescar()

    @staticmethod
    def _doc_texto(r):
        d = r.get("documentada_en") or ""
        return ("✓ Documentada " + d[5:16].replace("T", " ")) if d else "○ No documentada"

    def refrescar(self):
        sel = self._clave()
        f = self.cb_f.get()
        regs = self.sv.listar(self.q.get())
        if f == "No documentadas":
            regs = [r for r in regs if not r.get("documentada_en")]
        elif f == "Documentadas":
            regs = [r for r in regs if r.get("documentada_en")]
        fe = self.cb_e.get()
        if fe in ESTADOS:
            regs = [r for r in regs if estados.normalizar(r.get("resultado")) == fe]
        self.regs = regs
        for i in self.t.get_children():
            self.t.delete(i)
        for r in self.regs:
            self.t.insert("", "end", iid=r["key"], tags=("doc" if r.get("documentada_en") else "pend",), values=(
                r.get("id") or "—", r.get("rr"), r.get("cliente"), r.get("red"), r.get("capa2"),
                estados.normalizar(r.get("resultado")) or "—", r.get("estado"), self._doc_texto(r),
                (r.get("actualizada") or "")[5:16].replace("T", " ")))
        if sel and self.t.exists(sel):
            self.t.selection_set(sel)
        pend = sum(1 for r in self.regs if not r.get("documentada_en"))
        self.lbl.config(text="%d solicitud(es) · %d sin documentar" % (len(self.regs), pend))

    def _clave(self):
        sel = self.t.selection()
        return sel[0] if sel else None

    def _abrir(self):
        k = self._clave()
        rec = self.sv.store.cargar(k) if k else None
        if rec:
            self.abrir(rec)
            return rec

    def _abrir_documentar(self):
        """Reabre la plantilla guardada y lanza la documentación (Microsoft Forms)."""
        if self._abrir():
            self.after(200, lambda: self.winfo_toplevel().v_res._documentar())

    def _menu_estado(self):
        """Fija a mano Exitosa / Escalamiento / No exitosa a la solicitud seleccionada."""
        k = self._clave()
        if not k:
            return

        def poner(estado):
            self.sv.cambiar_resultado(k, estado)
            self.refrescar()

        menu_estado(self.b_estado, poner)

    def _ips_libres(self):
        """Reabre el recuadro de IPs/segmentos de la solicitud seleccionada."""
        if self._abrir():
            self.after(200, self.winfo_toplevel().v_res.abrir_ips)   # acción explícita del botón

    def _alternar(self):
        k = self._clave()
        rec = self.sv.store.cargar(k) if k else None
        if not rec:
            return
        from datetime import datetime
        nuevo = "" if rec.get("documentada_en") else datetime.now().isoformat(timespec="seconds")
        self.sv.actualizar(k, documentada_en=nuevo)
        self.refrescar()

    def _eliminar(self):
        k = self._clave()
        if k and messagebox.askyesno("Eliminar", "¿Eliminar la solicitud %s del historial? (No borra el .txt)" % k):
            self.sv.store.eliminar(k)
            self.refrescar()


# ======================================================================================= IP CAPA 2
class PanelIPs(tk.Frame):
    COLS = ("Equipo", "Tipo", "IP", "Fuente", "Usos", "Última vez")

    def __init__(self, padre, servicio):
        super().__init__(padre, bg=C["bg"])
        self.sv = servicio
        tk.Label(self, text="Memoria de IP de Capa 2", bg=C["bg"], fg=C["txt"], font=(SERIF, 17, "bold")).pack(anchor="w")
        _ayuda(self, "Es el archivo historial_capa2.json que usa el script: si el equipo está aquí, entra "
               "solo; si no, se pide la IP una vez y queda guardada.")
        f = tk.Frame(self, bg=C["bg"])
        f.pack(fill="x")
        self.q = _entry(f)
        self.q.pack(side="left", fill="x", expand=True, ipady=5)
        self.q.bind("<KeyRelease>", lambda e: self.refrescar())
        BOTON(f, "Eliminar", self._eliminar, False, 9).pack(side="left", padx=(8, 0))
        m, self.t = _tabla(self, self.COLS, (260, 60, 130, 90, 60, 150), alto=10)
        m.pack(fill="both", expand=True, pady=8)
        tk.Label(self, text="Agregar o actualizar (una línea por equipo:  NOMBRE  IP):", bg=C["bg"], fg=C["mut"],
                 font=(FONT, 9, "bold")).pack(anchor="w")
        self.txt = tk.Text(self, height=4, bg=C["card2"], fg=C["txt"], relief="flat", font=("Consolas", 10),
                           insertbackground=C["txt"])
        self.txt.pack(fill="x")
        b = tk.Frame(self, bg=C["bg"])
        b.pack(fill="x", pady=6)
        BOTON(b, "Importar texto", self._importar, True, 14).pack(side="left")
        BOTON(b, "Importar archivo…", self._archivo, False, 16).pack(side="left", padx=6)
        self.lbl = tk.Label(b, text="", bg=C["bg"], fg=C["mut"], font=(FONT, 9))
        self.lbl.pack(side="left", padx=8)
        self.refrescar()

    def refrescar(self):
        f = self.q.get().strip().lower()
        for i in self.t.get_children():
            self.t.delete(i)
        for r in self.sv.ips.listar():
            if f and f not in ("%s %s" % (r.get("nombre", ""), r.get("ip", ""))).lower():
                continue
            self.t.insert("", "end", iid=r.get("nombre"), values=(
                r.get("nombre"), r.get("tipo"), r.get("ip"), r.get("fuente"), r.get("veces"),
                (r.get("ultima") or "").replace("T", " ")))

    def _resumen(self, r):
        self.lbl.config(text="Nuevas %d · actualizadas %d · iguales %d · inválidas %d" % (
            r["nuevas"], r["actualizadas"], r["iguales"], len(r["invalidas"])))
        self.refrescar()

    def _importar(self):
        self._resumen(self.sv.ips.importar_texto(self.txt.get("1.0", "end")))

    def _archivo(self):
        ruta = filedialog.askopenfilename(filetypes=[("Texto/CSV/JSON", "*.txt *.csv *.json"), ("Todos", "*.*")])
        if ruta:
            self._resumen(self.sv.ips.importar_archivo(ruta))

    def _eliminar(self):
        sel = self.t.selection()
        if sel and messagebox.askyesno("Eliminar", "¿Quitar %s de la memoria de IP?" % sel[0]):
            self.sv.ips.eliminar(sel[0])
            self.refrescar()


# ======================================================================================= AJUSTES
class PanelAjustes(tk.Frame):
    """Ajustes: carpeta de plantillas, credenciales y (opcional) funciones avanzadas."""

    def __init__(self, padre, servicio=None):
        super().__init__(padre, bg=C["bg"])
        self.sv = servicio
        self.al_modo = None          # la App lo usa para mostrar/ocultar las pestañas avanzadas
        tk.Label(self, text="Ajustes", bg=C["bg"], fg=C["txt"], font=(SERIF, 17, "bold")).pack(anchor="w")
        self.campos = {}
        self._carpeta_card()
        self._bloque("Support Portal", "Usuario y clave para consultar el portal.",
                     (("portal_usuario", "Usuario", False), ("portal_clave", "Clave", True)))
        self._bloque("Microsoft (SharePoint y correo)", "Para entrar solo. El número de verificación lo aprueba usted en el celular.",
                     (("ms_usuario", "Correo", False), ("ms_clave", "Clave (opcional)", True)))
        self._bloque("SecureCRT", "Usuario y clave para entrar a los equipos.",
                     (("crt_usuario", "Usuario", False), ("crt_clave", "Clave", True)))
        # ---- avanzado
        self.avz = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Mostrar funciones avanzadas (Cola, Admin, IP Capa 2)", variable=self.avz,
                       command=self._cambiar_modo, bg=C["bg"], fg=C["txt"], activebackground=C["bg"],
                       selectcolor=C["card"], font=(FONT, 10), bd=0, highlightthickness=0).pack(anchor="w", pady=(4, 6))
        self.caja_avz = tk.Frame(self, bg=C["bg"])
        self._padre_bloque = self.caja_avz
        self._bloque("Mi nombre en SharePoint", "Tal como aparece en PEM_ASIGNADO.", (("pem_nombre", "Nombre", False),))
        self._bloque("Ruta de SecureCRT", "SecureCRT.exe, para abrirlo solo desde la Cola.", (("securecrt_exe", "Ruta", False),))
        self._padre_bloque = self
        self.auto = tk.BooleanVar(value=False)
        tk.Checkbutton(self.caja_avz, text="Asignarme una solicitud libre cuando no tenga ninguna", variable=self.auto,
                       bg=C["bg"], fg=C["txt"], activebackground=C["bg"], selectcolor=C["card"],
                       font=(FONT, 10), bd=0, highlightthickness=0).pack(anchor="w")
        barra = ad.Flujo(self, C["bg"])
        barra.pack(fill="x", pady=(10, 0))
        BOTON(barra, "Guardar", self._guardar, True, 12).pack(side="left")
        self.ver = tk.BooleanVar(value=False)
        tk.Checkbutton(barra, text="Mostrar claves", variable=self.ver, command=self._ver, bg=C["bg"],
                       fg=C["mut"], activebackground=C["bg"], selectcolor=C["card"], font=(FONT, 10),
                       bd=0, highlightthickness=0).pack(side="left", padx=14)
        self.lbl = tk.Label(barra, text="", bg=C["bg"], fg=C["ok"], font=(FONT, 10))
        self.lbl.pack(side="left")
        self.refrescar()

    # ---- carpeta de plantillas
    def _carpeta_card(self):
        card = tk.Frame(self, bg=C["card"], highlightbackground=C["line"], highlightcolor=C["line"], highlightthickness=1)
        card.pack(fill="x", pady=(8, 10))
        inner = tk.Frame(card, bg=C["card"])
        inner.pack(fill="x", padx=22, pady=16)
        tk.Label(inner, text="¿Dónde guardar las plantillas?", bg=C["card"], fg=C["txt"],
                 font=(FONT, 12, "bold")).pack(anchor="w")
        l = tk.Label(inner, text="Elija una carpeta (puede ser de OneDrive o una unidad de red).", bg=C["card"],
                     fg=C["mut"], font=(FONT, 9), justify="left", anchor="w")
        l.pack(fill="x", pady=(0, 8))
        ad.envolver(l, 44)
        fila = tk.Frame(inner, bg=C["card"])
        fila.pack(fill="x")
        self.e_carpeta = _entry(fila)
        self.e_carpeta.pack(side="left", fill="x", expand=True, ipady=5)
        self.e_carpeta.bind("<KeyRelease>", lambda e: self._ejemplo())
        BOTON(fila, "Examinar…", self._examinar, True, 11).pack(side="left", padx=(8, 0))
        BOTON(fila, "Abrir", self._abrir_carpeta, False, 7).pack(side="left", padx=(6, 0))
        self.sub = tk.BooleanVar(value=True)
        tk.Checkbutton(inner, text="Crear una subcarpeta por día (mes-día)", variable=self.sub, command=self._ejemplo,
                       bg=C["card"], fg=C["txt"], activebackground=C["card"], selectcolor=C["card2"],
                       font=(FONT, 10), bd=0, highlightthickness=0).pack(anchor="w", pady=(8, 0))
        self.l_ej = tk.Label(inner, text="", bg=C["card"], fg=C["mut"], font=(FONT, 9), justify="left", anchor="w")
        self.l_ej.pack(fill="x", pady=(4, 0))
        ad.envolver(self.l_ej, 44)

    def _carpeta_actual(self):
        from . import plantilla as pl
        return str(pl.carpeta_base(self.e_carpeta.get().strip()))

    def _ejemplo(self):
        from . import plantilla as pl
        fmt = "%m-%d" if self.sub.get() else "-"
        r = pl.ruta_destino(self.e_carpeta.get().strip(), fmt, "12345678", "CLIENTE")
        self.l_ej.config(text="Ejemplo: %s" % r)

    def _examinar(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Carpeta para guardar las plantillas", initialdir=self._carpeta_actual()
                                    if os.path.isdir(self._carpeta_actual()) else os.path.expanduser("~"))
        if d:
            self.e_carpeta.delete(0, "end")
            self.e_carpeta.insert(0, os.path.normpath(d))
            self._ejemplo()

    def _abrir_carpeta(self):
        d = self._carpeta_actual()
        try:
            os.makedirs(d, exist_ok=True)
            if os.name == "nt":
                os.startfile(d)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", d])
        except Exception as ex:
            self.lbl.config(text="No se pudo abrir: %s" % ex, fg=C["err"])

    def _cambiar_modo(self):
        self._mostrar_avz()
        if self.sv:
            from .servicio import guardar_ajustes
            self.sv.ajustes["modo_avanzado"] = bool(self.avz.get())
            guardar_ajustes(self.sv.ajustes)
        if self.al_modo:
            self.al_modo(bool(self.avz.get()))

    def _mostrar_avz(self):
        if self.avz.get():
            self.caja_avz.pack(fill="x", before=self._barra_ref())
        else:
            self.caja_avz.pack_forget()

    def _barra_ref(self):
        return [w for w in self.pack_slaves()][-1]

    def _bloque(self, titulo, ayuda, campos):
        card = tk.Frame(self._padre_bloque if hasattr(self, "_padre_bloque") else self, bg=C["card"],
                        highlightbackground=C["line"], highlightcolor=C["line"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))
        inner = tk.Frame(card, bg=C["card"])
        inner.pack(fill="x", padx=22, pady=14)
        tk.Label(inner, text=titulo, bg=C["card"], fg=C["txt"], font=(FONT, 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        l = tk.Label(inner, text=ayuda, bg=C["card"], fg=C["mut"], font=(FONT, 9), justify="left", anchor="w")
        l.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for col, (clave, nombre, secreto) in enumerate(campos):
            tk.Label(inner, text=nombre, bg=C["card"], fg=C["mut"], font=(FONT, 9, "bold")).grid(row=2, column=col, sticky="w", padx=(0 if col == 0 else 12, 0))
            e = _entry(inner, width=26, show="•" if secreto else "")
            e.grid(row=3, column=col, sticky="w", ipady=5, padx=(0 if col == 0 else 12, 0))
            e._secreto = secreto
            self.campos[clave] = e
            if clave == "securecrt_exe":
                e.config(width=48)
                BOTON(inner, "Examinar…", lambda en=e: self._examinar_exe(en), False, 10).grid(row=3, column=1, sticky="w", padx=(8, 0))

    def _examinar_exe(self, entrada):
        r = filedialog.askopenfilename(title="Seleccione SecureCRT (SecureCRTPortable.exe o SecureCRT.exe)",
                                       filetypes=[("Programa", "*.exe")])
        if r:
            entrada.delete(0, "end")
            entrada.insert(0, os.path.normpath(r))

    def _ver(self):
        for e in self.campos.values():
            if e._secreto:
                e.config(show="" if self.ver.get() else "•")

    def refrescar(self):
        datos = credenciales.cargar()
        aj = self.sv.ajustes if self.sv else {}
        datos["pem_nombre"] = aj.get("pem_nombre", "")
        datos["securecrt_exe"] = aj.get("securecrt_exe", "")
        self.auto.set(bool(aj.get("auto_asignar", False)))
        self.sub.set(bool(aj.get("subcarpeta_dia", True)))
        self.avz.set(bool(aj.get("modo_avanzado", False)))
        self.e_carpeta.delete(0, "end")
        self.e_carpeta.insert(0, aj.get("carpeta_plantillas", ""))
        for k, e in self.campos.items():
            e.delete(0, "end")
            e.insert(0, datos.get(k, ""))
        self._ejemplo()
        self._mostrar_avz()

    def _guardar(self):
        try:
            credenciales.guardar({k: e.get() for k, e in self.campos.items() if k in credenciales.CAMPOS})
            if self.sv:
                from .servicio import guardar_ajustes
                carpeta = self.e_carpeta.get().strip()
                if carpeta:
                    os.makedirs(carpeta, exist_ok=True)
                self.sv.ajustes["carpeta_plantillas"] = carpeta
                self.sv.ajustes["subcarpeta_dia"] = bool(self.sub.get())
                self.sv.ajustes["pem_nombre"] = self.campos["pem_nombre"].get().strip()
                self.sv.ajustes["securecrt_exe"] = self.campos["securecrt_exe"].get().strip()
                self.sv.ajustes["auto_asignar"] = bool(self.auto.get())
                guardar_ajustes(self.sv.ajustes)
            self.lbl.config(text="Guardado", fg=C["ok"])
        except Exception as ex:
            self.lbl.config(text="No se pudo guardar: %s" % ex, fg=C["err"])
