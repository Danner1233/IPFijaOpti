# -*- coding: utf-8 -*-
"""
hac_zac_gui.py  -  Interfaz del proceso HAC / ZAC.

La lanza SCRIPT_HAC_ZAC_UNIFICADO.py (SecureCRT) y se comunica con el por
archivos JSON en una carpeta temporal:

    solicitud.json  (GUI -> script)  serial/mac, megas, bridge
    estado.json     (script -> GUI)  paso actual, mensajes, resultado, error
    respuesta.json  (GUI -> script)  respuesta a una pregunta (IP del Capa 2)
    cancelar.flag   (GUI -> script)  detener al terminar el paso actual

Prueba visual sin SecureCRT:   python hac_zac_gui.py --demo
Requiere Python 3 con tkinter (viene con el instalador de python.org).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from hac_zac import adaptable as ad
from hac_zac import cola, panel, panel_centro, sesion, plantilla as plt
from hac_zac.rutas import data_dir
from hac_zac.servicio import Servicio

# Windows: pantalla nitida y tamanos correctos con zoom (125 %, 150 %...) y alta resolucion.
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

SERIAL_PREFIJOS = ("ZTE", "SEI", "SDM", "SERC", "SKY", "HWTC")

C = dict(   # Oscuro futurista (estilo Claude): negro calido, un acento terracota
    bg="#0d0d0c", card="#171716", card2="#212120", line="#302f2c",
    txt="#f3f1ea", mut="#9b988f", acc="#d97757", acc_d="#c4623f",
    acc_soft="#3a2820", on_acc="#ffffff",
    ok="#6ec17f", warn="#e0a458", err="#e5675c",
)
FONT = "Segoe UI"
SERIF = "Georgia"   # titulos con serif, como la interfaz de Claude


# ----------------------------------------------------------------------
# Utilidades de archivos
# ----------------------------------------------------------------------
def leer_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def escribir_json(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=True)
    os.replace(tmp, ruta)


def tipo_valor(texto):
    t = texto.strip().upper()
    if not t:
        return ""
    return "SERIAL" if t.startswith(SERIAL_PREFIJOS) else "MAC"


# ----------------------------------------------------------------------
# Plantilla (PROVISIONAL - para pruebas)
# ----------------------------------------------------------------------
def construir_plantilla(r):
    def v(k, d="-"):
        x = r.get(k)
        return str(x) if x not in (None, "", []) else d

    ips = r.get("ips_libres_final") or r.get("ips_libres") or []
    lineas = [
        "===== DATOS DEL SERVICIO =====",
        "Cliente:      " + v("cliente"),
        "Cuenta RR:    " + v("rr"),
        "Serial ONT:   " + v("serial"),
        "MAC ONT:      " + v("mac"),
        "IP ONT:       " + v("ip_ont"),
        "Equipo:       " + (v("fabricante", "") + " " + v("modelo", "")).strip(),
        "",
        "===== RED =====",
        "Capa 3:       %s   (interfaz %s)" % (v("capa3"), v("interfaz")),
        "Capa 2:       %s (%s)   IP %s" % (v("capa2"), v("tipo_capa2"), v("ip_capa2")),
        "Gateway:      %s   Mascara: %s" % (v("gateway"), v("mascara")),
        "Dest/Mask:    " + v("destination_mask"),
        "",
        "===== CONFIGURACION =====",
        "Velocidad:    %sM   Bridge: %s" % (v("velocidad"), v("bridge")),
        "Descripcion:  " + v("descripcion"),
    ]
    if r.get("tipo_capa2") == "HAC":
        lineas += [
            "Service-port: %s   F/S/P: %s   ONT-ID: %s" % (
                v("service_port"), v("fs_p"), v("ont_id")),
            "TID DOWN/UP: %s / %s   CIR: %s kbps" % (
                v("tid_down"), v("tid_up"), v("cir")),
        ]
    elif r.get("gpon"):
        lineas += [
            "GPON:         " + v("gpon"),
            "VPORT:        " + v("vport"),
        ]
    if r.get("verificacion"):
        lineas.append("Verificacion: " + v("verificacion"))
    if r.get("nota"):
        lineas += ["", "NOTA: " + v("nota")]
    lineas += [
        "",
        "===== IPs LIBRES (%d) =====" % len(ips),
        ", ".join(ips) if ips else "Sin IPs en estado Incomplete",
        "",
        "Generado: " + time.strftime("%Y-%m-%d %H:%M"),
    ]
    return "\n".join(lineas)


# ----------------------------------------------------------------------
# Interfaz
# ----------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self, carpeta, demo=False, centro=False):
        super().__init__()
        self.carpeta = carpeta
        self.demo = demo
        self.centro = centro      # modo "centro de control": sin la pestana Operacion (no hay script esperando)
        self.seq_visto = -1
        self.bridge = tk.StringVar(value="NO")
        self.pregunta_id = None
        self.pasos_widgets = []
        self.barra_objetivo = 0.0
        self.angulo = 0
        self.corriendo = False
        self.ultimo_resultado = None
        self.inicio_run = ""
        self.rec_actual = None
        self.sv = Servicio()

        self.title("HAC / ZAC  -  Aprovisionamiento")
        self.configure(bg=C["bg"])
        ad.iniciar(self, float(os.environ.get("HAC_ZAC_ESCALA") or 0))
        self._centrar()

        self._estilos()
        self._header()
        self._scroll = ad.Scrollable(self, C["bg"])
        self._scroll.pack(fill="both", expand=True, padx=26, pady=(0, 16))
        self.cont = self._scroll.inner

        panel.configurar(C, FONT, self._boton)
        self.v_form = self._vista_form()
        self.v_run = self._vista_run()
        self.v_res = panel.PanelPlantilla(self.cont, self.sv, al_cambiar=lambda: self.v_hist.refrescar())
        self.v_hist = panel.PanelHistorial(self.cont, self.sv, self._abrir_solicitud)
        self.v_ips = panel.PanelIPs(self.cont, self.sv)
        self.v_aj = panel.PanelAjustes(self.cont, self.sv)
        self.v_aj.al_modo = self._cambio_modo
        self.v_cola = panel_centro.PanelCola(self.cont, self.sv, self._procesar_caso)
        self.v_cola.ocupado = lambda: self.corriendo
        self.v_admin = panel_centro.PanelAdmin(self.cont, self.sv)
        self.vista_op = self.v_form
        self._mostrar(self.v_cola if centro else self.v_form)
        if centro or not demo:
            self.after(1500, self.v_cola.iniciar_al_abrir)        # lectores de SharePoint y correo (si esta marcado)
        if not centro and not demo:
            self.after(700, self._cargar_caso_pendiente)
            self._latir()                                          # avisa que esta ventana esta viva y recibe casos

        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        # Al abrir, Windows aun no ha dado su tamano final a la ventana cuando se calcula el diseno: sin esto
        # hay que maximizar y restaurar para ver todo. Se fuerza un recalculo cuando la ventana ya esta mostrada.
        self.bind("<Map>", self._al_mostrar, add="+")
        for ms in (60, 250, 700):
            self.after(ms, self._relayout)
        self.after(250, self._poll)
        self.after(40, self._animar)

    # ---------- base ----------
    def _al_mostrar(self, e=None):
        if e is not None and e.widget is not self:
            return
        self.after_idle(self._relayout)

    def _relayout(self):
        """Recalcula pestanas, scroll y vistas con el tamano real de la ventana (equivale a maximizar y restaurar)."""
        try:
            self.update_idletasks()
            w, h = self.winfo_width(), self.winfo_height()
            if w > 1 and h > 1:
                self.geometry("%dx%d" % (w, h))        # fija el tamano real y fuerza un nuevo ciclo de diseno
            self.update_idletasks()
            self._h2._reflujo()
            self._scroll._ajustar()
            self._pintar_linea()
        except Exception:
            pass

    def _centrar(self):
        self.update_idletasks()
        w, h, x, y = ad.tamano_ventana(self, 1100, 800)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.minsize(min(ad.px(700), w), min(ad.px(500), h))

    def _estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Vertical.TScrollbar", background=C["card2"], troughcolor=C["bg"], bordercolor=C["bg"],
                    lightcolor=C["card2"], darkcolor=C["card2"], arrowcolor=C["mut"], gripcount=0, relief="flat")
        s.map("Vertical.TScrollbar", background=[("active", C["line"])])
        s.configure("Barra.Horizontal.TProgressbar", troughcolor=C["card2"],
                    background=C["acc"], bordercolor=C["card2"],
                    lightcolor=C["acc"], darkcolor=C["acc"], thickness=10)

    def _header(self):
        h = tk.Frame(self, bg=C["bg"])
        h.pack(fill="x", padx=26, pady=(16, 4))
        tk.Label(h, text="HAC  ·  ZAC", bg=C["bg"], fg=C["txt"],
                 font=(SERIF, 22, "bold")).pack(side="left")
        sub = tk.Label(h, text="  Aprovisionamiento automático", bg=C["bg"],
                       fg=C["mut"], font=(FONT, 11))
        sub.pack(side="left", pady=(8, 0))
        self.pill = tk.Label(h, text="  Listo  ", bg=C["card2"], fg=C["mut"],
                             font=(FONT, 9, "bold"), padx=8, pady=3)
        self.pill.pack(side="right")
        b_ips = tk.Label(h, text="IPs libres", bg=C["card2"], fg=C["acc"], font=(FONT, 10, "bold"),
                         padx=10, pady=3, cursor="hand2")
        b_ips.pack(side="right", padx=(8, 0))
        b_ips.bind("<Button-1>", lambda e: self._ips_libres())
        self.b_nueva = tk.Label(h, text="＋ Nueva solicitud", bg=C["acc"], fg=C["on_acc"], font=(FONT, 10, "bold"),
                                padx=10, pady=3, cursor="hand2")
        if not self.centro:
            self.b_nueva.pack(side="right", padx=(8, 0))
        self.b_nueva.bind("<Button-1>", lambda e: self._nueva_solicitud())
        # el subtitulo se oculta si la ventana es angosta
        h.bind("<Configure>", lambda e: (sub.pack_forget() if e.width < ad.px(640) else
                                         (sub.pack(side="left", pady=(8, 0)) if not sub.winfo_ismapped() else None)))
        # pestanas en su propia fila; si no caben, se reparten en varias
        h2 = ad.Flujo(self, C["bg"], hueco=2)
        h2.pack(fill="x", padx=26, pady=(0, 8))
        self.tabs = {}
        self._h2 = h2
        for nombre in ("Operación", "Cola", "Historial", "IP Capa 2", "Admin", "Ajustes"):
            t = tk.Label(h2, text=nombre, bg=C["bg"], fg=C["mut"], font=(FONT, 11, "bold"),
                         padx=10, pady=2, cursor="hand2")
            t.bind("<Button-1>", lambda e, n=nombre: self._tab(n))
            self.tabs[nombre] = t
        self._pestanas()
        self._linea = tk.Canvas(self, height=2, bg=C["bg"], highlightthickness=0)
        self._linea.pack(fill="x", padx=26, pady=(0, 8))
        self._linea.bind("<Configure>", self._pintar_linea)

    def _nueva_solicitud(self):
        """Deja el formulario limpio para otra solicitud (el script ya volvio al jump host y espera)."""
        if self.corriendo:
            messagebox.showinfo("En proceso", "Hay una solicitud en proceso. Espere a que termine o cancele.")
            return
        v = getattr(self.v_res, "ventana_ips", None)
        if v and v.winfo_exists():
            v.destroy()
        self.t_sol.delete("1.0", "end")
        self.e_valor.delete(0, "end")
        self.e_megas.delete(0, "end")
        self._set_bridge("NO")
        self.l_sol.config(text="")
        self.lbl_err.config(text="")
        self._firma_sol = None
        self.rec_actual = None
        self._mostrar(self.v_form)
        self.t_sol.focus_set()

    def _pestanas(self):
        """Modo sencillo: Operación, Cola, Historial y Ajustes. Modo avanzado: agrega IP Capa 2 y Admin."""
        avz = self.centro or bool(self.sv.ajustes.get("modo_avanzado", False))
        sencillas = ("Operación", "Cola", "Historial", "Ajustes")
        for n, t in self.tabs.items():
            t.pack_forget()
            t.grid_forget()
            if self.centro and n == "Operación":
                continue
            if avz or n in sencillas:
                t.pack(side="left")
        self._h2.event_generate("<Configure>")

    def _cambio_modo(self, avanzado):
        self._pestanas()
        if not avanzado and not self.centro:
            self._tab("Ajustes")
        self._mostrar(self.v_aj)

    def _pintar_linea(self, e=None):
        """Linea fina con degradado acento -> fondo (toque futurista)."""
        c = self._linea
        c.delete("all")
        w = max(c.winfo_width(), 2)
        a = [int(C["acc"][i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(C["line"][i:i + 2], 16) for i in (1, 3, 5)]
        n = 60
        for i in range(n):
            t = i / (n - 1)
            col = "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))
            c.create_rectangle(w * i / n, 0, w * (i + 1) / n + 1, 2, fill=col, outline=col)

    def _pill(self, texto, color):
        self.pill.config(text="  %s  " % texto, fg=color)

    def _card(self, padre, **kw):
        return tk.Frame(padre, bg=C["card"], highlightbackground=C["line"], highlightcolor=C["line"],
                        highlightthickness=1, **kw)

    def _boton(self, padre, texto, cmd, primario=True, ancho=16):
        bg = C["acc"] if primario else C["card2"]
        fg = C["on_acc"] if primario else C["txt"]
        b = tk.Label(padre, text=texto, bg=bg, fg=fg, font=(FONT, 11, "bold"),
                     width=ancho, pady=9, cursor="hand2")
        hov = C["acc_d"] if primario else C["line"]
        b.bind("<Enter>", lambda e: b.config(bg=hov))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _mostrar(self, vista):
        for v in (self.v_form, self.v_run, self.v_res, self.v_hist, self.v_ips, self.v_aj, self.v_cola, self.v_admin):
            v.pack_forget()
        vista.pack(fill="both", expand=True)
        self.after_idle(self._relayout)
        if vista in (self.v_form, self.v_run, self.v_res):
            self.vista_op = vista
            activa = "Operación"
        else:
            activa = {id(self.v_hist): "Historial", id(self.v_aj): "Ajustes", id(self.v_cola): "Cola",
                      id(self.v_admin): "Admin"}.get(id(vista), "IP Capa 2")
        for n, t in self.tabs.items():
            t.config(fg=C["acc"] if n == activa else C["mut"])

    def _tab(self, nombre):
        if nombre == "Operación":
            self._mostrar(self.vista_op)
        elif nombre == "Historial":
            self.v_hist.refrescar()
            self._mostrar(self.v_hist)
        elif nombre == "Ajustes":
            self.v_aj.refrescar()
            self._mostrar(self.v_aj)
        elif nombre == "Cola":
            self.v_cola.refrescar()
            self._mostrar(self.v_cola)
        elif nombre == "Admin":
            self.v_admin.refrescar()
            self._mostrar(self.v_admin)
        else:
            self.v_ips.refrescar()
            self._mostrar(self.v_ips)

    def _ips_libres(self):
        """Reabre el recuadro de segmentos/IP libres (de la solicitud abierta o la mas reciente)."""
        if not getattr(self.v_res, "rec", None):
            regs = self.sv.listar("")
            rec = self.sv.store.cargar(regs[0]["key"]) if regs else None
            if not rec:
                messagebox.showinfo("IP libres", "Todavia no hay solicitudes con IP libres.")
                return
            self.v_res.cargar(rec)
        self.v_res.abrir_ips()

    # ---------- cola -> script ----------
    def _procesar_caso(self, s):
        """Procesa un caso de la cola SIN abrir otro script ni otro SecureCRT:
        * en la ventana del script: carga los datos y arranca;
        * en el Centro de control: si hay una ventana de script viva le pasa el caso; solo si no hay ninguna abre SecureCRT."""
        import subprocess
        d = s["datos"]
        caso = {"txt_sol": d.get("txt_sol", ""), "auto": True, "id": s["id"]}
        if not self.centro:
            if self.corriendo:
                messagebox.showinfo("En proceso", "Hay una solicitud en proceso. Cuando termine, pulse Procesar de nuevo.")
                return
            cola.cambiar_estado(s["id"], "en_proceso")
            self._aplicar_caso(caso)
            self.v_cola.refrescar()
            return
        cola.cambiar_estado(s["id"], "en_proceso")
        self.v_cola.refrescar()
        if sesion.hay_ventana_viva():
            sesion.enviar_caso(caso)
            return
        escribir_json(str(data_dir() / "caso_pendiente.json"), caso)
        exe = (self.sv.ajustes.get("securecrt_exe") or "").strip()
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SCRIPT_HAC_ZAC_UNIFICADO.py")
        if exe and os.path.exists(exe):
            subprocess.Popen([exe, "/SCRIPT", script])
        else:
            messagebox.showinfo("Procesar", "El caso quedó listo. Abra SecureCRT y ejecute el script "
                                "SCRIPT_HAC_ZAC_UNIFICADO.py: arrancará solo con la solicitud %s.\n\n"
                                "(Para que se abra solo, escriba la ruta de SecureCRT.exe en Ajustes.)" % s["id"])

    def _latir(self):
        """Cada pocos segundos: avisa que esta ventana esta viva y recoge el caso que le hayan mandado."""
        try:
            sesion.latir()
            if not self.corriendo:
                caso = sesion.tomar_caso()
                if caso:
                    self._aplicar_caso(caso)
                    self.v_cola.refrescar()
        except Exception:
            pass
        self.after(3000, self._latir)

    def _aplicar_caso(self, caso):
        """Pasa los datos del caso al formulario y arranca una nueva solicitud en el script que ya esta abierto."""
        self._nueva_solicitud()
        self.t_sol.insert("1.0", caso.get("txt_sol", ""))
        self._leer_solicitud()
        self._mostrar(self.v_form)
        if caso.get("auto"):
            self.after(900, self._iniciar)

    def _cargar_caso_pendiente(self):
        """Si la Cola dejo un caso (script recien abierto), llena el formulario con la plantilla y arranca."""
        ruta = str(data_dir() / "caso_pendiente.json")
        caso = leer_json(ruta)
        if not caso:
            return
        try:
            os.replace(ruta, ruta + ".usado")
        except OSError:
            pass
        self._aplicar_caso(caso)

    def _abrir_solicitud(self, rec):
        self.rec_actual = rec
        self.v_res.cargar(rec)
        self._mostrar(self.v_res)

    # ---------- vista 1: formulario ----------
    def _vista_form(self):
        f = tk.Frame(self.cont, bg=C["bg"])
        card = self._card(f)
        card.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(card, bg=C["card"])
        inner.pack(fill="x", padx=28, pady=26)

        tk.Label(inner, text="Serial o MAC de la ONT", bg=C["card"], fg=C["mut"],
                 font=(FONT, 10)).grid(row=0, column=0, sticky="w")
        fila = tk.Frame(inner, bg=C["card"])
        fila.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 18))
        inner.columnconfigure(0, weight=1)

        self.e_valor = tk.Entry(fila, bg=C["card2"], fg=C["txt"], relief="flat",
                                insertbackground=C["txt"], font=(FONT, 16),
                                highlightthickness=1, highlightbackground=C["line"],
                                highlightcolor=C["acc"])
        self.e_valor.pack(side="left", fill="x", expand=True, ipady=9)
        self.badge = tk.Label(fila, text="  -  ", bg=C["card2"], fg=C["mut"],
                              font=(FONT, 10, "bold"), width=9)
        self.badge.pack(side="left", padx=(10, 0), ipady=10)
        self.e_valor.bind("<KeyRelease>", lambda e: self._badge())

        tk.Label(inner, text="Megas", bg=C["card"], fg=C["mut"],
                 font=(FONT, 10)).grid(row=2, column=0, sticky="w")
        tk.Label(inner, text="Bridge", bg=C["card"], fg=C["mut"],
                 font=(FONT, 10)).grid(row=2, column=1, sticky="w", padx=(30, 0))

        self.e_megas = tk.Entry(inner, bg=C["card2"], fg=C["txt"], relief="flat",
                                insertbackground=C["txt"], font=(FONT, 16), width=10,
                                highlightthickness=1, highlightbackground=C["line"],
                                highlightcolor=C["acc"])
        self.e_megas.grid(row=3, column=0, sticky="w", pady=(4, 0), ipady=9)

        seg = tk.Frame(inner, bg=C["card"])
        seg.grid(row=3, column=1, sticky="w", padx=(30, 0), pady=(4, 0))
        self.seg = {}
        for txt in ("SI", "NO"):
            l = tk.Label(seg, text=txt, width=7, pady=11, cursor="hand2",
                         font=(FONT, 11, "bold"))
            l.pack(side="left", padx=(0, 6))
            l.bind("<Button-1>", lambda e, t=txt: self._set_bridge(t))
            self.seg[txt] = l
        self._set_bridge("NO")

        tk.Label(inner, text="Datos de la solicitud (obligatorio: pegue el bloque DATOS DE CONFIGURACIÓN)",
                 bg=C["card"], fg=C["mut"], font=(FONT, 10)).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(16, 0))
        self.t_sol = tk.Text(inner, height=6, bg=C["card2"], fg=C["txt"], relief="flat",
                             font=("Consolas", 9), insertbackground=C["txt"])
        self.t_sol.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.t_sol.bind("<KeyRelease>", lambda e: self._leer_solicitud())
        # pegar con el mouse (clic derecho / menú) no genera tecla: también se lee
        self.t_sol.bind("<<Paste>>", lambda e: self.after(80, self._leer_solicitud))
        self.t_sol.bind("<ButtonRelease-2>", lambda e: self.after(80, self._leer_solicitud))
        self.l_sol = tk.Label(inner, text="", bg=C["card"], fg=C["acc"], font=(FONT, 9), anchor="w")
        self.l_sol.grid(row=6, column=0, columnspan=2, sticky="w")

        self.lbl_err = tk.Label(inner, text="", bg=C["card"], fg=C["err"],
                                font=(FONT, 10))
        self.lbl_err.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self._boton(inner, "Iniciar proceso", self._iniciar, ancho=22).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))

        tk.Label(f, text="El resto de los datos (IP de la ONT, cliente y RR) los "
                         "toma solo el Support Portal.",
                 bg=C["bg"], fg=C["mut"], font=(FONT, 10)).pack(anchor="w", pady=14)
        self.e_valor.bind("<Return>", lambda e: self._iniciar())
        self.e_megas.bind("<Return>", lambda e: self._iniciar())
        self.after(300, self.e_valor.focus_set)
        return f

    def _set_bridge(self, val):
        self.bridge.set(val)
        for t, l in self.seg.items():
            if t == val:
                l.config(bg=C["acc"], fg=C["on_acc"])
            else:
                l.config(bg=C["card2"], fg=C["mut"])

    def _badge(self):
        t = tipo_valor(self.e_valor.get())
        if t == "SERIAL":
            self.badge.config(text="SERIAL", fg=C["ok"])
        elif t == "MAC":
            self.badge.config(text="MAC", fg=C["acc"])
        else:
            self.badge.config(text="  -  ", fg=C["mut"])

    def _leer_solicitud(self):
        """Pegó la solicitud: de ahí salen MAC/serial, megas, bridge e ID (se actualiza si pega otra)."""
        crudo = self.t_sol.get("1.0", "end")
        if plt.es_fila_sp(crudo):                 # fila copiada de SharePoint -> plantilla de siempre
            self.t_sol.delete("1.0", "end")
            self.t_sol.insert("1.0", plt.desde_fila_sp(crudo))
        s = plt.parsear_solicitud(self.t_sol.get("1.0", "end"))
        if not (s["solicitud_id"] or s["rr"]):
            self.l_sol.config(text="")
            return
        # MAC ONT si viene; si no, SERIAL ONT (el script decide MAC/serial por el prefijo)
        valor = plt.normalizar_sn(s["mac_ont"]) or plt.normalizar_sn(s["serial_ont"])
        firma = (s["solicitud_id"], s["rr"], valor, s["ancho_banda"], s["bridge"])
        if firma != getattr(self, "_firma_sol", None):
            self._firma_sol = firma
            if valor:
                self.e_valor.delete(0, "end")
                self.e_valor.insert(0, valor)
                self._badge()
            if s["ancho_banda"]:
                self.e_megas.delete(0, "end")
                self.e_megas.insert(0, s["ancho_banda"])
            if s["bridge"] is not None:
                self._set_bridge("SI" if s["bridge"] else "NO")
        t = tipo_valor(self.e_valor.get())
        self.l_sol.config(text="Solicitud %s · RR %s · %s · %s %s · %sM · Bridge %s" % (
            s["solicitud_id"] or "—", s["rr"] or "—", s["cliente"] or "—", t or "—",
            self.e_valor.get() or "", self.e_megas.get() or "—", self.bridge.get()))

    def _iniciar(self):
        self._leer_solicitud()          # por si se pego sin que se leyera (llena MAC/serial, megas y bridge)
        valor = self.e_valor.get().strip()
        megas = self.e_megas.get().strip()
        sol = plt.parsear_solicitud(self.t_sol.get("1.0", "end"))
        if not sol["solicitud_id"] or not sol["rr"]:
            self.lbl_err.config(text="Pegue la solicitud: debe traer SOLICITUD ID y CUENTA RR.")
            return
        if not valor:
            self.lbl_err.config(text="La solicitud no trae MAC ni serial: escríbalo arriba.")
            return
        if not megas.isdigit():
            self.lbl_err.config(text="Las megas deben ser un numero entero. Ej: 950")
            return
        self.lbl_err.config(text="")
        escribir_json(os.path.join(self.carpeta, "solicitud.json"), {
            "valor": valor, "megas": megas, "bridge": self.bridge.get(),
            "txt_sol": self.t_sol.get("1.0", "end").strip(),
            "solicitud_id": plt.parsear_solicitud(self.t_sol.get("1.0", "end"))["solicitud_id"]})
        self.inicio_run = datetime.now().isoformat()
        self.rec_actual = None
        self._preparar_run("Conectando con SecureCRT...")
        self.corriendo = True

    # ---------- vista 2: proceso ----------
    def _vista_run(self):
        f = tk.Frame(self.cont, bg=C["bg"])
        card = self._card(f)
        card.pack(fill="both", expand=True, pady=(10, 0))
        top = tk.Frame(card, bg=C["card"])
        top.pack(fill="x", padx=28, pady=(26, 8))

        d, a0, a1, ancho = ad.px(84), ad.px(10), ad.px(74), ad.px(7)
        self.cv = tk.Canvas(top, width=d, height=d, bg=C["card"],
                            highlightthickness=0)
        self.cv.pack(side="left")
        self.cv.create_oval(a0, a0, a1, a1, outline=C["card2"], width=ancho)
        self.arco = self.cv.create_arc(a0, a0, a1, a1, start=0, extent=110,
                                       style="arc", outline=C["acc"], width=ancho)

        txt = tk.Frame(top, bg=C["card"])
        txt.pack(side="left", padx=20, fill="x", expand=True)
        self.l_msg = tk.Label(txt, text="", bg=C["card"], fg=C["txt"],
                              font=(SERIF, 17, "bold"), anchor="w", justify="left")
        self.l_msg.pack(fill="x")
        self.l_sub = tk.Label(txt, text="", bg=C["card"], fg=C["mut"],
                              font=(FONT, 10), anchor="w")
        self.l_sub.pack(fill="x", pady=(4, 0))

        self.barra = ttk.Progressbar(card, style="Barra.Horizontal.TProgressbar",
                                     maximum=100, mode="determinate")
        self.barra.pack(fill="x", padx=28, pady=(14, 14))

        self.cont_pasos = tk.Frame(card, bg=C["card"])
        self.cont_pasos.pack(fill="x", padx=28)

        # Pregunta en linea (IP del Capa 2)
        self.ask = tk.Frame(card, bg=C["card2"], highlightbackground=C["line"],
                            highlightcolor=C["line"], highlightthickness=1)
        self.ask_msg = tk.Label(self.ask, text="", bg=C["card2"], fg=C["txt"],
                                font=(FONT, 10), justify="left", wraplength=ad.px(760),
                                anchor="w")
        self.ask_msg.pack(fill="x", padx=16, pady=(12, 6))
        ad.envolver(self.ask_msg, margen=40)
        self.ask_err = tk.Label(self.ask, text="", bg=C["card2"], fg=C["err"],
                                font=(FONT, 10), anchor="w")
        self.ask_err.pack(fill="x", padx=16)
        fila = tk.Frame(self.ask, bg=C["card2"])
        fila.pack(fill="x", padx=16, pady=(4, 14))
        self.e_ask = tk.Entry(fila, bg=C["card"], fg=C["txt"], relief="flat",
                              insertbackground=C["txt"], font=(FONT, 13), width=22,
                              highlightthickness=1, highlightbackground=C["line"],
                              highlightcolor=C["acc"])
        self.e_ask.pack(side="left", ipady=6)
        self.e_ask.bind("<Return>", lambda e: self._responder(True))
        self._boton(fila, "Continuar", lambda: self._responder(True),
                    ancho=12).pack(side="left", padx=10)
        self._boton(fila, "Cancelar", lambda: self._responder(False),
                    primario=False, ancho=12).pack(side="left")

        # Detalle
        pie = tk.Frame(card, bg=C["card"])
        pie.pack(side="bottom", fill="x", padx=28, pady=(8, 20))
        self.l_det = tk.Label(pie, text="Ver detalle", bg=C["card"], fg=C["acc"],
                              font=(FONT, 10, "underline"), cursor="hand2")
        self.l_det.pack(side="left")
        self.l_det.bind("<Button-1>", lambda e: self._toggle_log())
        self.b_sol = tk.Label(pie, text="Abrir en Plantilla / Historial", bg=C["card"], fg=C["acc"],
                              font=(FONT, 10, "underline"), cursor="hand2")
        self.b_sol.bind("<Button-1>", lambda e: self.rec_actual and self._abrir_solicitud(self.rec_actual))
        self._boton(pie, "Cancelar", self._cancelar, primario=False,
                    ancho=12).pack(side="right")

        self.txt_log = tk.Text(card, height=8, bg=C["bg"], fg=C["mut"],
                               relief="flat", font=("Consolas", 9), wrap="word")
        self.log_visible = False
        return f

    def _toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.txt_log.pack(fill="x", padx=28, pady=(0, 6), before=self.l_det.master)
            self.l_det.config(text="Ocultar detalle")
        else:
            self.txt_log.pack_forget()
            self.l_det.config(text="Ver detalle")

    def _preparar_run(self, msg):
        self._mostrar(self.v_run)
        self.l_msg.config(text=msg)
        self.l_sub.config(text="")
        self.barra["value"] = 0
        self.barra_objetivo = 0
        self.ask.pack_forget()
        self.b_sol.pack_forget()
        self.l_msg.config(fg=C["txt"])
        self._pill("En proceso", C["acc"])
        self.attributes("-topmost", True)

    def _armar_pasos(self, pasos):
        for w in self.cont_pasos.winfo_children():
            w.destroy()
        self.pasos_widgets = []
        for i, nombre in enumerate(pasos):
            fila = tk.Frame(self.cont_pasos, bg=C["card"])
            fila.pack(fill="x", pady=2)
            ic = tk.Label(fila, text="○", bg=C["card"], fg=C["mut"],
                          font=(FONT, 12), width=2)
            ic.pack(side="left")
            tx = tk.Label(fila, text=nombre, bg=C["card"], fg=C["mut"],
                          font=(FONT, 11), anchor="w")
            tx.pack(side="left")
            self.pasos_widgets.append((ic, tx))

    def _marcar_pasos(self, actual, fase):
        for i, (ic, tx) in enumerate(self.pasos_widgets, start=1):
            if fase == "fin" or i < actual:
                ic.config(text="✔", fg=C["ok"]); tx.config(fg=C["txt"])
            elif i == actual and fase in ("corriendo", "pregunta"):
                ic.config(text="●", fg=C["acc"]); tx.config(fg=C["txt"])
            elif i == actual and fase == "error":
                ic.config(text="✖", fg=C["err"]); tx.config(fg=C["err"])
            else:
                ic.config(text="○", fg=C["mut"]); tx.config(fg=C["mut"])

    def _cancelar(self):
        open(os.path.join(self.carpeta, "cancelar.flag"), "w").close()
        self.l_sub.config(text="Cancelando al terminar el paso actual...")

    def _responder(self, ok):
        if self.pregunta_id is None:
            return
        ip = self.e_ask.get().strip() if ok else ""
        escribir_json(os.path.join(self.carpeta, "respuesta.json"),
                      {"id": self.pregunta_id, "ip": ip})
        self.pregunta_id = None
        self.ask.pack_forget()
        self.ask_err.config(text="")
        self.e_ask.delete(0, "end")

    # ---------- estado ----------
    def _poll(self):
        e = leer_json(os.path.join(self.carpeta, "estado.json"))
        if e and e.get("seq", -1) != self.seq_visto:
            self.seq_visto = e["seq"]
            self._aplicar(e)
        self.after(250, self._poll)

    def _aplicar(self, e):
        fase = e.get("fase")
        if fase == "esperando":
            return
        if not self.corriendo and fase in ("corriendo", "pregunta"):
            self.corriendo = True
            self._preparar_run("Iniciando...")

        if e.get("pasos") and len(e["pasos"]) != len(self.pasos_widgets):
            self._armar_pasos(e["pasos"])

        total = max(1, len(e.get("pasos") or [1]))
        paso = int(e.get("paso") or 0)

        # log
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        for l in e.get("log", [])[-120:]:
            self.txt_log.insert("end", "%s  %s\n" % (l.get("t", ""), l.get("m", "")))
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

        if fase == "corriendo":
            self.l_msg.config(text=e.get("mensaje") or "Procesando...")
            self.l_sub.config(text="Paso %d de %d" % (paso, total))
            self.barra_objetivo = (paso - 0.5) / total * 100
            self._marcar_pasos(paso, fase)
            self.ask.pack_forget()

        elif fase == "pregunta":
            p = e.get("pregunta") or {}
            self.l_msg.config(text="Se necesita un dato")
            self.l_sub.config(text="Paso %d de %d" % (paso, total))
            self._marcar_pasos(paso, fase)
            if self.pregunta_id != p.get("id"):
                self.pregunta_id = p.get("id")
                self.ask_msg.config(text=(p.get("mensaje", "") or "").replace("\n\n", "\n"))
                self.ask_err.config(text=p.get("error") or "")
                self.ask.pack(fill="x", padx=28, pady=(14, 0))
                self.e_ask.focus_set()
                self.bell()

        elif fase == "fin":
            self.corriendo = False
            self.attributes("-topmost", False)
            self.barra_objetivo = 100
            self._marcar_pasos(total, "fin")
            r = e.get("resultado") or {}
            self.ultimo_resultado = r
            rec = self._registrar("fin", r, e.get("mensaje") or "Proceso finalizado")
            if rec:
                self._abrir_solicitud(rec)
                self._pill("Completado", C["ok"])
                self.v_res.resaltar_segmentos()            # sin ventana emergente: doble clic en el segmento
            else:
                self.l_msg.config(text="Completado, pero sin ID ni cuenta RR para guardar en el historial")

        elif fase == "error":
            self.corriendo = False
            self.attributes("-topmost", False)
            self._marcar_pasos(paso, "error")
            self.l_msg.config(text="El proceso se detuvo", fg=C["err"])
            self.l_sub.config(text=(e.get("error") or "")[:300])
            self.ask.pack_forget()
            self._pill("Error", C["err"])
            if not self.log_visible:
                self._toggle_log()
            rec = self._registrar("error", e.get("resultado") or {}, e.get("error") or "Error")
            self._ofrecer_solicitud(rec)
            self._mostrar(self.v_run)

        elif fase == "cancelado":
            self.corriendo = False
            self.attributes("-topmost", False)
            self.l_msg.config(text="Proceso cancelado")
            self.l_sub.config(text="")
            self._pill("Cancelado", C["warn"])
            rec = self._registrar("cancelado", e.get("resultado") or {}, "Cancelado por el operador")
            self._ofrecer_solicitud(rec)

    def _registrar(self, fase, resultado, mensaje):
        """Guarda el intento en el historial de solicitudes (si hay ID o cuenta RR)."""
        try:
            rec = self.sv.registrar_operacion(fase, resultado, mensaje,
                                              self.inicio_run or datetime.now().isoformat())
        except Exception as ex:
            self.l_sub.config(text="No se pudo guardar en el historial: %s" % ex)
            return None
        self.rec_actual = rec
        try:        # la solicitud de la cola: 'por documentar' si salio bien (pasa a terminada al DOCUMENTAR); si no, vuelve a 'asignada' para reintentar
            sid = str((resultado or {}).get("solicitud_id") or "")
            if sid:
                cola.cambiar_estado(sid, "por_documentar" if fase == "fin" else "asignada")
        except Exception:
            pass
        self.v_hist.refrescar()
        return rec

    def _ofrecer_solicitud(self, rec):
        if rec:
            self.b_sol.pack(side="left", padx=14)
        else:
            self.b_sol.pack_forget()

    def _animar(self):
        if self.corriendo:
            self.angulo = (self.angulo + 9) % 360
            self.cv.itemconfig(self.arco, start=self.angulo)
        actual = float(self.barra["value"])
        if abs(self.barra_objetivo - actual) > 0.2:
            self.barra["value"] = actual + (self.barra_objetivo - actual) * 0.12
        self.after(35, self._animar)

    def _cerrar(self):
        if not self.centro:
            sesion.apagar()
        for v in (self.v_cola, self.v_admin):          # lectores y agente en segundo plano
            try:
                v.detener_todo()
            except Exception:
                pass
        try:
            if not self.demo:
                shutil.rmtree(self.carpeta, ignore_errors=True)
        except Exception:
            pass
        self.destroy()


# ----------------------------------------------------------------------
# Modo demo (simula al script de SecureCRT para ver el diseño)
# ----------------------------------------------------------------------
PASOS = [
    "Consultando el Support Portal",
    "Entrando al A9K y descubriendo el Capa 3",
    "Leyendo ruta, interfaz y Capa 2",
    "Buscando IPs libres",
    "Entrando al Capa 2",
    "Configurando velocidad y descripcion",
    "Verificando y cerrando",
]


def demo_hilo(carpeta):
    seq = [0]
    log = []

    def est(fase, paso, msg="", **extra):
        seq[0] += 1
        log.append({"t": time.strftime("%H:%M:%S"), "n": "info", "m": msg or fase})
        d = {"seq": seq[0], "fase": fase, "paso": paso, "pasos": PASOS,
             "mensaje": msg, "log": log, "pregunta": None, "resultado": None,
             "error": None}
        d.update(extra)
        escribir_json(os.path.join(carpeta, "estado.json"), d)

    est("esperando", 0)
    while not os.path.exists(os.path.join(carpeta, "solicitud.json")):
        time.sleep(0.3)
    sol = leer_json(os.path.join(carpeta, "solicitud.json"))
    textos = [
        "Consultando el Support Portal", "Entrando al A9K",
        "Leyendo la interfaz del Capa 3", "Buscando IPs libres",
        "Entrando al Capa 2", "Configurando la ONT", "Verificando",
    ]
    for i, t in enumerate(textos, start=1):
        est("corriendo", i, t)
        time.sleep(1.4)
        if i == 5:
            est("pregunta", i, "Pregunta IP Capa 2", pregunta={
                "id": 1, "mensaje": "Este Capa 2 no esta en la base.\n\nEquipo: "
                "HAC-DEMO.1 (HAC)\n\nIngrese la IP del Capa 2.", "error": None})
            while not os.path.exists(os.path.join(carpeta, "respuesta.json")):
                time.sleep(0.3)
    cfg = ("interface GE1/0/1.1201\n description ZAC-DEMO.1\n ip address 10.115.227.1 255.255.255.0\n"
           " ip address 10.115.230.1 255.255.255.128 sub\n")
    res = {
        "cliente": "ANGI DAYAN GALINDO CUESTA", "rr": "64217507", "solicitud_id": sol.get("solicitud_id") or "61901",
        "txt_sol": sol.get("txt_sol", ""),
        "serial": sol["valor"], "mac": "68:2a:dd:98:fe:3b", "ip_ont": "10.115.227.29",
        "capa3_inicial": "A9KTRIARA2", "capa3": "172.30.10.5", "interfaz": "GE1/0/1.1201",
        "interfaz_encontrada": "GE1/0/1.1950", "capa2": "ZAC-DEMO.1", "tipo_capa2": "ZAC",
        "ip_capa2": "172.30.165.202", "gateway": "10.115.227.1", "mascara": "255.255.255.0",
        "velocidad": sol["megas"], "bridge": sol["bridge"],
        "descripcion": "ANGI_DAYAN_GALINDO_CUESTA_64217507", "gpon": "gpon_onu-1/2/15:18", "vport": "1/2/15.18:1",
        "bloque_interfaz": cfg, "configurado": True, "verificacion": "Configuracion final consultada",
        "ips_libres": ["10.115.227.40", "10.115.227.41", "10.115.227.45", "10.115.230.20"],
        "cmd_config": "service-port 5 user-vlan 201 vlan 201 ingress INTERNET-BA-IP-%sM-UP egress INTERNET-BA-IP-%sM-DOWN" % (sol["megas"], sol["megas"]),
        "cmd_security": "security max-mac-learn 5", "cmd_bridge": "vlan port eth_0/4 mode hybrid def-vlan 201",
        "raw": {"gpon_pre": " name VIEJO\n description VIEJO\n", "vport_pre": " service-port 5 user-vlan 201 vlan 201\n",
                "gpon_post": " vlan port eth_0/4 mode hybrid def-vlan 201\n", "vport_post": " security max-mac-learn 5\n"},
        "portal": {"crudo": {"User name": "ANGI DAYAN GALINDO CUESTA", "mycust04": "64217507", "Serial number": sol["valor"],
                             "IP address": "10.115.227.29", "Product class": "F6601P"}},
    }
    est("fin", len(PASOS), "Completado", resultado=res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="carpeta de sesion (la pasa SecureCRT)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--centro", action="store_true", help="centro de control: cola, lectores y administrador")
    a = ap.parse_args()

    if a.demo:
        os.environ["HAC_ZAC_DATOS"] = tempfile.mkdtemp(prefix="hac_zac_datos_demo_")   # no toca su historial real
        carpeta = tempfile.mkdtemp(prefix="hac_zac_demo_")
        threading.Thread(target=demo_hilo, args=(carpeta,), daemon=True).start()
    elif a.centro:
        carpeta = tempfile.mkdtemp(prefix="hac_zac_centro_")
    elif a.dir:
        carpeta = a.dir
    else:
        print("Use --dir <carpeta> (lo hace SecureCRT) o --demo para ver el diseno.")
        return 1

    App(carpeta, demo=a.demo, centro=a.centro).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
