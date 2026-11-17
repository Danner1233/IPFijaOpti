# -*- coding: utf-8 -*-
"""Centro de control: 'Cola' (mis solicitudes + lectores) y 'Admin' (ingenieros + agente administrador)."""
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from . import cola
from . import panel as P
from .servicios import Proceso


class _Servicios(tk.Frame):
    """Filas con luz de estado + Iniciar/Detener para cada proceso, y una consola de salida."""

    def __init__(self, padre, filas, sv, extra_args):
        super().__init__(padre, bg=P.C["bg"])
        self.sv, self.extra_args = sv, extra_args
        self.procesos = {}
        card = tk.Frame(self, bg=P.C["card"], highlightbackground=P.C["line"], highlightcolor=P.C["line"],
                        highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=P.C["card"])
        inner.pack(fill="x", padx=18, pady=12)
        self.luz, self.btn = {}, {}
        for i, (clave, titulo, script) in enumerate(filas):
            self.procesos[clave] = Proceso(titulo, script)
            self.luz[clave] = tk.Label(inner, text="●", bg=P.C["card"], fg=P.C["mut"], font=(P.FONT, 12))
            self.luz[clave].grid(row=i, column=0, sticky="w")
            tk.Label(inner, text=titulo, bg=P.C["card"], fg=P.C["txt"], font=(P.FONT, 11, "bold"),
                     width=24, anchor="w").grid(row=i, column=1, sticky="w", padx=(6, 10), pady=3)
            b = tk.Label(inner, text="Iniciar", bg=P.C["acc"], fg=P.C["on_acc"], font=(P.FONT, 10, "bold"),
                         width=10, pady=4, cursor="hand2")
            b.grid(row=i, column=2, sticky="w")
            b.bind("<Button-1>", lambda e, k=clave: self._alternar(k))
            self.btn[clave] = b
        self.var_ver = tk.BooleanVar(value=False)
        self.opciones = P.ad.Flujo(inner, P.C["card"], hueco=4)
        self.opciones.grid(row=len(filas), column=0, columnspan=4, sticky="ew", pady=(8, 0))
        inner.columnconfigure(3, weight=1)
        tk.Checkbutton(self.opciones, text="Primera vez: esperar inicio de sesión", variable=self.var_ver,
                       bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                       font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left")
        self.b_enter = tk.Label(self.opciones, text="Ya inicié sesión", bg=P.C["card2"], fg=P.C["txt"],
                                font=(P.FONT, 10, "bold"), padx=10, pady=3, cursor="hand2")
        self.b_enter.pack(side="left", padx=12)
        self.b_enter.bind("<Button-1>", lambda e: self._enter())

        self.txt = tk.Text(self, height=7, bg=P.C["bg"], fg=P.C["mut"], relief="flat", font=("Consolas", 9),
                           state="disabled", wrap="word", highlightthickness=1, highlightbackground=P.C["line"],
                           highlightcolor=P.C["line"])
        self.txt.pack(fill="both", expand=True, pady=(8, 0))
        self.after(400, self._vigilar)

    def _alternar(self, clave):
        pr = self.procesos[clave]
        if pr.vivo():
            pr.detener()
            return
        args = self.extra_args(clave)
        if args is None:
            return
        pr.iniciar(args + (["--ver"] if self.var_ver.get() else []), ver=self.var_ver.get())

    def _enter(self):
        for pr in self.procesos.values():
            if pr.vivo() and pr.espera_enter:
                pr.enter()

    def _vigilar(self):
        if not self.winfo_exists():
            return
        for k, pr in self.procesos.items():
            vivo = pr.vivo()
            self.luz[k].config(fg=P.C["ok"] if vivo else P.C["mut"])
            self.btn[k].config(text="Detener" if vivo else "Iniciar",
                               bg=P.C["card2"] if vivo else P.C["acc"], fg=P.C["txt"] if vivo else P.C["on_acc"])
            try:
                while True:
                    self._escribir(pr.nombre, pr.salida.get_nowait())
            except queue.Empty:
                pass
        esperando = any(p.vivo() and p.espera_enter for p in self.procesos.values())
        self.b_enter.config(bg=P.C["acc"] if esperando else P.C["card2"], fg=P.C["on_acc"] if esperando else P.C["mut"])
        self.after(400, self._vigilar)

    def _escribir(self, nombre, linea):
        self.txt.config(state="normal")
        self.txt.insert("end", "[%s] %s\n" % (nombre.split()[0], linea))
        if int(self.txt.index("end-1c").split(".")[0]) > 400:
            self.txt.delete("1.0", "100.0")
        self.txt.see("end")
        self.txt.config(state="disabled")

    def detener_todo(self):
        for pr in self.procesos.values():
            pr.detener()

    def hay_vivos(self):
        return any(pr.vivo() for pr in self.procesos.values())

    def iniciar_todo(self, ver):
        """Arranca los procesos escalonados (6 s entre uno y otro): dos Selenium arrancando a la vez se pisan
        al preparar el driver de Chrome."""
        pend = []
        for k, pr in self.procesos.items():
            if pr.vivo():
                continue
            args = self.extra_args(k)
            if args is None:
                return False
            pend.append((pr, args + (["--ver"] if ver else [])))
        for i, (pr, args) in enumerate(pend):
            if i == 0:
                pr.iniciar(args, ver=ver)
            else:
                self.after(6000 * i, lambda p=pr, a=args: (None if p.vivo() else p.iniciar(a, ver=ver)))
        return True


def _titulo(padre, texto, ayuda):
    tk.Label(padre, text=texto, bg=P.C["bg"], fg=P.C["txt"], font=(P.SERIF, 17, "bold")).pack(anchor="w")
    a = tk.Label(padre, text=ayuda, bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 10), justify="left")
    a.pack(anchor="w", pady=(0, 8))
    P.ad.envolver(a)


# ======================================================================================= COLA
class PanelCola(tk.Frame):
    COLS = ("Solicitud", "Cuenta RR", "Cliente", "Estado", "Plantilla", "SharePoint", "Correo", "Demora")

    def __init__(self, padre, servicio, procesar):
        super().__init__(padre, bg=P.C["bg"])
        self.sv, self.procesar = servicio, procesar
        _titulo(self, "Mis solicitudes", "Los lectores traen las solicitudes que se le asignan a su nombre y copian "
                "su plantilla del correo. Cuando una tiene plantilla, pulse Procesar: se abre SecureCRT y el script arranca solo.")
        self.auto = tk.BooleanVar(value=bool(servicio.ajustes.get("auto_asignar", True)))
        self.b_flujo = P.BOTON(self, "▶  Iniciar flujo (SharePoint + correo)", self._flujo, True, 34)
        self.b_flujo.pack(anchor="w", pady=(0, 8))
        self.serv = _Servicios(self, (("sp", "Lector de SharePoint", "sp_lector.py"),
                                      ("correo", "Lector de correo", "correo_lector.py")), servicio, self._args)
        tk.Checkbutton(self.serv.opciones, text="Asignarme solo una solicitud libre", variable=self.auto,
                       command=self._guardar_auto,
                       bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                       font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left", padx=(12, 0))
        self.auto_proc = tk.BooleanVar(value=bool(servicio.ajustes.get("auto_procesar", False)))
        tk.Checkbutton(self.serv.opciones, text="Procesar solo cuando llegue la plantilla", variable=self.auto_proc,
                       command=self._guardar_auto, bg=P.C["card"], fg=P.C["acc"], activebackground=P.C["card"],
                       selectcolor=P.C["bg"], font=(P.FONT, 10, "bold"), bd=0,
                       highlightthickness=0).pack(side="left", padx=(12, 0))
        self.al_abrir = tk.BooleanVar(value=bool(servicio.ajustes.get("flujo_al_abrir", False)))
        tk.Checkbutton(self.serv.opciones, text="Iniciar el flujo al abrir", variable=self.al_abrir,
                       command=self._guardar_auto, bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"],
                       selectcolor=P.C["bg"], font=(P.FONT, 10), bd=0,
                       highlightthickness=0).pack(side="left", padx=(12, 0))
        tk.Label(self.serv.opciones, text="Ver navegador:", bg=P.C["card"], fg=P.C["mut"],
                 font=(P.FONT, 10)).pack(side="left", padx=(14, 2))
        self.ver = {}
        for clave, nombre in (("sp", "SharePoint"), ("correo", "Correo"), ("portal", "Portal")):
            v = tk.BooleanVar(value=bool(servicio.ajustes.get("ver_" + clave, True)))
            self.ver[clave] = v
            tk.Checkbutton(self.serv.opciones, text=nombre, variable=v, command=self._guardar_auto,
                           bg=P.C["card"], fg=P.C["txt"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                           font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left", padx=(6, 0))
        self.serv.pack(fill="x")
        b = P.ad.Flujo(self, P.C["bg"])
        b.pack(fill="x", pady=(10, 0))
        P.BOTON(b, "Procesar", self._procesar, True, 11).pack(side="left")
        P.BOTON(b, "Marcar terminada", self._terminar, False, 16).pack(side="left", padx=6)
        P.BOTON(b, "Quitar de la cola", self._quitar, False, 15).pack(side="left")
        m, self.t = P._tabla(self, self.COLS, (80, 95, 200, 95, 75, 120, 120, 80), alto=7)
        m.pack(fill="both", expand=True, pady=8)
        self.t.bind("<Double-1>", lambda e: self._procesar())
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w")
        self.lbl.pack(fill="x")
        self.refrescar()

    def _args(self, clave):
        if clave == "correo":
            return []
        nombre = (self.sv.ajustes.get("pem_nombre") or "").strip()
        if not nombre:
            messagebox.showinfo("Mi nombre", "Escriba su nombre como aparece en PEM_ASIGNADO en la pestaña Ajustes.")
            return None
        return ["--nombre", nombre] + (["--tomar"] if self.auto.get() else [])

    @staticmethod
    def _hora(iso):
        return (iso or "")[11:19] if iso and "T" in iso else (iso or "—")

    def refrescar(self):
        if not self.winfo_exists():
            return
        sel = self.t.selection()
        for i in self.t.get_children():
            self.t.delete(i)
        for s in reversed(cola.solicitudes()):
            d = s["datos"]
            dem = s.get("demora_correo_s")
            self.t.insert("", "end", iid=s["id"], values=(
                s["id"], d.get("rr", ""), d.get("cliente", ""), s["estado"].replace("_", " "),
                "✓" if s.get("plantilla") else "—", self._hora(d.get("creada") or s.get("recibida")),
                self._hora(s.get("correo_en")), ("%d:%02d" % divmod(dem, 60)) if dem is not None else "—"))
        if sel and self.t.exists(sel[0]):
            self.t.selection_set(sel[0])
        abiertas = [s for s in cola.solicitudes() if s["estado"] in cola.ABIERTOS]
        self.lbl.config(text="%d abierta(s)" % len(abiertas))
        self._auto_procesar()
        self._pintar_flujo()
        self.after(3000, self.refrescar)

    def _flujo(self):
        """Un solo boton: abre/cierra el lector de SharePoint y el de correo a la vez."""
        if self.serv.hay_vivos():
            self.serv.detener_todo()
        else:
            self.serv.iniciar_todo(self.serv.var_ver.get())
        self._pintar_flujo()

    def _pintar_flujo(self):
        vivo = self.serv.hay_vivos()
        self.b_flujo.config(text="■  Detener flujo" if vivo else "▶  Iniciar flujo (SharePoint + correo)",
                            bg=P.C["card2"] if vivo else P.C["acc"], fg=P.C["txt"] if vivo else P.C["on_acc"])

    def iniciar_al_abrir(self):
        if self.al_abrir.get() and not self.serv.hay_vivos():
            self.serv.iniciar_todo(False)

    def _guardar_auto(self):
        from hac_zac.servicio import guardar_ajustes
        self.sv.ajustes["auto_procesar"] = bool(self.auto_proc.get())
        self.sv.ajustes["auto_asignar"] = bool(self.auto.get())
        self.sv.ajustes["flujo_al_abrir"] = bool(self.al_abrir.get())
        for k, v in self.ver.items():
            self.sv.ajustes["ver_" + k] = bool(v.get())
        guardar_ajustes(self.sv.ajustes)

    def _auto_procesar(self):
        """Modo desatendido: si no hay un caso corriendo, toma el siguiente asignado a mi nombre que ya tiene
        su plantilla del correo y lo manda al script."""
        if not self.auto_proc.get():
            return
        if getattr(self, "ocupado", None) and self.ocupado():      # ya hay un proceso corriendo en esta ventana
            return
        todas = cola.solicitudes()
        if any(x["estado"] == "en_proceso" for x in todas):
            return
        sig = next((x for x in todas if x["estado"] == "asignada" and x.get("plantilla")), None)
        if sig:
            self.procesar(sig)

    def _caso(self):
        sel = self.t.selection()
        return next((s for s in cola.solicitudes() if sel and s["id"] == sel[0]), None)

    def _procesar(self):
        s = self._caso()
        if not s:
            return
        if not s.get("plantilla"):
            messagebox.showinfo("Procesar", "Esta solicitud todavía no tiene la plantilla del correo.\n"
                                "Verifique que el Lector de correo esté iniciado.")
            return
        self.procesar(s)

    def _terminar(self):
        s = self._caso()
        if s:
            cola.cambiar_estado(s["id"], "terminada")
            self.refrescar()

    def _quitar(self):
        s = self._caso()
        if s and messagebox.askyesno("Quitar", "¿Quitar la solicitud %s de la cola? (No toca SharePoint)" % s["id"]):
            c = cola._cola()
            c["solicitudes"] = [x for x in c["solicitudes"] if x["id"] != s["id"]]
            cola._escribir("cola.json", c)
            self.refrescar()

    def detener_todo(self):
        self.serv.detener_todo()


# ======================================================================================= ADMIN
class PanelAdmin(tk.Frame):
    def __init__(self, padre, servicio):
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        _titulo(self, "Administrador", "Active a los ingenieros que pueden recibir solicitudes. El agente reparte la "
                "solicitud libre más antigua al ingeniero activo que no tenga ninguna abierta. El nombre debe ser exactamente "
                "el de PEM_ASIGNADO.")
        top = P.ad.Flujo(self, P.C["bg"])
        top.pack(fill="x")
        self.e_nuevo = P._entry(top, width=30)
        self.e_nuevo.pack(side="left", ipady=5)
        self.e_nuevo.bind("<Return>", lambda e: self._agregar())
        P.BOTON(top, "Agregar", self._agregar, True, 10).pack(side="left", padx=6)
        P.BOTON(top, "Activar / Desactivar", self._alternar, False, 20).pack(side="left")
        P.BOTON(top, "Quitar", self._quitar, False, 9).pack(side="right")
        m, self.t = P._tabla(self, ("Ingeniero", "Estado", "Última asignación"), (320, 120, 200), alto=7)
        m.pack(fill="x", pady=8)
        self.t.tag_configure("on", foreground=P.C["ok"])
        self.t.tag_configure("off", foreground=P.C["mut"])
        self.t.bind("<Double-1>", lambda e: self._alternar())
        self.sim = tk.BooleanVar(value=False)
        self.serv = _Servicios(self, (("admin", "Agente administrador", "admin_agente.py"),), servicio, self._args)
        tk.Checkbutton(self.serv.opciones, text="Simulación (no escribe en SharePoint)", variable=self.sim,
                       bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                       font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left", padx=(12, 0))
        self.serv.pack(fill="both", expand=True)
        self.refrescar()

    def _args(self, clave):
        if not [i for i in cola.ingenieros() if i.get("activo")]:
            messagebox.showinfo("Administrador", "No hay ingenieros activos. Active al menos uno.")
            return None
        return ["--simular"] if self.sim.get() else []

    def refrescar(self):
        sel = self.t.selection()
        for i in self.t.get_children():
            self.t.delete(i)
        for i in cola.ingenieros():
            self.t.insert("", "end", iid=i["nombre"], tags=("on" if i.get("activo") else "off",),
                          values=(i["nombre"], "● Activo" if i.get("activo") else "○ Inactivo",
                                  (i.get("ultimo") or "—").replace("T", " ")[5:16]))
        if sel and self.t.exists(sel[0]):
            self.t.selection_set(sel[0])

    def _agregar(self):
        n = self.e_nuevo.get().strip()
        if n:
            cola.agregar_ingeniero(n)
            self.e_nuevo.delete(0, "end")
            self.refrescar()

    def _alternar(self):
        sel = self.t.selection()
        if sel:
            actual = next((i for i in cola.ingenieros() if i["nombre"] == sel[0]), {})
            cola.poner_activo(sel[0], not actual.get("activo"))
            self.refrescar()

    def _quitar(self):
        sel = self.t.selection()
        if sel and messagebox.askyesno("Quitar", "¿Quitar a %s de la lista?" % sel[0]):
            cola.quitar_ingeniero(sel[0])
            self.refrescar()

    def detener_todo(self):
        self.serv.detener_todo()
