# -*- coding: utf-8 -*-
"""Centro de control: 'Cola' (mis solicitudes + lectores) y 'Admin' (ingenieros + agente administrador)."""
import queue
import tkinter as tk
from tkinter import messagebox

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
    COLS = ("Solicitud", "Cuenta RR", "Cliente", "Estado", "Plantilla", "SharePoint", "Correo", "Demora", "Tiempo")

    def __init__(self, padre, servicio, procesar):
        super().__init__(padre, bg=P.C["bg"])
        self.sv, self.procesar = servicio, procesar
        from . import central_cliente
        self.central = central_cliente.configurado(servicio.ajustes)
        if self.central:
            _titulo(self, "Mis solicitudes", "El servidor central le asigna las solicitudes cuando está Disponible y "
                    "le trae la plantilla del correo (no tiene que abrir SharePoint ni Outlook). Cuando la solicitud "
                    "tenga plantilla, pulse Procesar.")
            self._tarjeta_central(central_cliente)
        else:
            _titulo(self, "Mis solicitudes", "Los lectores traen las solicitudes que se le asignan a su nombre y copian "
                    "su plantilla del correo. Cuando una tiene plantilla, pulse Procesar: se abre SecureCRT y el script "
                    "arranca solo.")
        self.auto = tk.BooleanVar(value=bool(servicio.ajustes.get("auto_asignar", True)))
        self.b_flujo = P.BOTON(self, "▶  Iniciar flujo (correo)" if self.central else
                               "▶  Iniciar flujo (SharePoint + correo)", self._flujo, True, 34)
        if not self.central:                       # con central: SharePoint y correo los atiende el servidor
            self.b_flujo.pack(anchor="w", pady=(0, 8))
        filas =((("correo", "Lector de correo", "correo_lector.py"),) if self.central else
                 (("sp", "Lector de SharePoint", "sp_lector.py"), ("correo", "Lector de correo", "correo_lector.py")))
        self.serv = _Servicios(self, filas, servicio, self._args)
        if not self.central:                       # con reparto central, asignar lo hace el servidor
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
        P.BOTON(b, "Liberar (Sin Asignar)", self._liberar, False, 20).pack(side="left", padx=6)
        m, self.t = P._tabla(self, self.COLS, (80, 95, 200, 95, 75, 120, 120, 80, 95), alto=7)
        m.pack(fill="both", expand=True, pady=8)
        self.t.tag_configure("excedida", foreground=P.C["err"])
        self.t.bind("<Double-1>", lambda e: self._procesar())
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w")
        self.lbl.pack(fill="x")
        if self.central:
            self._tarjeta_tecnico()
            self.t.bind("<<TreeviewSelect>>", lambda e: self._pintar_chat(forzar=True), add="+")
        self.refrescar()

    # ---------------------------------------------------------------- reparto central
    def _tarjeta_central(self, central_cliente):
        card = tk.Frame(self, bg=P.C["card"], highlightbackground=P.C["line"], highlightcolor=P.C["line"],
                        highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))
        fila = P.ad.Flujo(card, P.C["card"], hueco=8)
        fila.pack(fill="x", padx=18, pady=12)
        self.luz_central = tk.Label(fila, text="●", bg=P.C["card"], fg=P.C["mut"], font=(P.FONT, 12))
        self.luz_central.pack(side="left")
        tk.Label(fila, text="Reparto central", bg=P.C["card"], fg=P.C["txt"],
                 font=(P.FONT, 11, "bold")).pack(side="left", padx=(6, 14))
        self.b_disp = tk.Label(fila, text="", font=(P.FONT, 10, "bold"), padx=14, pady=5, cursor="hand2")
        self.b_disp.pack(side="left")
        self.b_disp.bind("<Button-1>", lambda e: self._alternar_disponible())
        self.lbl_central = tk.Label(fila, text="Conectando…", bg=P.C["card"], fg=P.C["mut"], font=(P.FONT, 10))
        self.lbl_central.pack(side="left", padx=(14, 0))
        self.disponible = False                     # al abrir siempre NO disponible: el PEM decide cuando empezar
        self._pintar_disponible()
        self.conexion = central_cliente.Conexion(self.sv.ajustes, lambda est: self.after(0, self._estado_central, est))
        self.conexion.iniciar()

    def _tarjeta_tecnico(self):
        """Conversacion con el tecnico de la solicitud seleccionada. El PEM no chatea: el agente le reenvia LITERAL
        lo que se escriba aqui, y le trae lo que el tecnico pregunte."""
        card = tk.Frame(self, bg=P.C["card"], highlightbackground=P.C["line"], highlightcolor=P.C["line"],
                        highlightthickness=1)
        card.pack(fill="both", expand=True, pady=(8, 0))
        inner = tk.Frame(card, bg=P.C["card"])
        inner.pack(fill="both", expand=True, padx=18, pady=12)
        self.lbl_tec = tk.Label(inner, text="Técnico: seleccione una solicitud", bg=P.C["card"], fg=P.C["txt"],
                                font=(P.FONT, 11, "bold"), anchor="w")
        self.lbl_tec.pack(fill="x")
        self.chat = tk.Text(inner, height=7, bg=P.C["bg"], fg=P.C["txt"], relief="flat", font=(P.FONT, 10),
                            state="disabled", wrap="word", highlightthickness=1, highlightbackground=P.C["line"])
        self.chat.pack(fill="both", expand=True, pady=(6, 6))
        for tag, color in (("tecnico", P.C["acc"]), ("agente", P.C["mut"]), ("pem", P.C["ok"]), ("pend", P.C["warn"])):
            self.chat.tag_configure(tag, foreground=color)
        tk.Label(inner, text="Mensaje para el técnico (se envía tal cual por WhatsApp):", bg=P.C["card"],
                 fg=P.C["mut"], font=(P.FONT, 9), anchor="w").pack(fill="x")
        self.e_msg = tk.Text(inner, height=3, bg=P.C["card2"], fg=P.C["txt"], insertbackground=P.C["txt"],
                             relief="flat", font=(P.FONT, 10), wrap="word")
        self.e_msg.pack(fill="x", pady=(2, 6))
        b = P.ad.Flujo(inner, P.C["card"])
        b.pack(fill="x")
        P.BOTON(b, "Enviar mensaje", lambda: self._enviar_tecnico("mensaje"), False, 15).pack(side="left")
        P.BOTON(b, "Enviar direccionamiento final", lambda: self._enviar_tecnico("direccionamiento"),
                True, 26).pack(side="left", padx=6)
        self.lbl_envio = tk.Label(inner, text="", bg=P.C["card"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w")
        self.lbl_envio.pack(fill="x", pady=(4, 0))
        self._firma_chat = None

    def _pintar_chat(self, forzar=False):
        if not getattr(self, "chat", None):
            return
        s = self._caso()
        firma = (s["id"], len(s.get("chat") or []), len(s.get("para_pem") or [])) if s else None
        if firma == self._firma_chat and not forzar:
            return
        self._firma_chat = firma
        self.chat.config(state="normal")
        self.chat.delete("1.0", "end")
        if not s:
            self.lbl_tec.config(text="Técnico: seleccione una solicitud")
        else:
            d = s["datos"]
            self.lbl_tec.config(text="Técnico de la %s: %s · %s" % (s["id"], d.get("tecnico") or "—",
                                                                  d.get("celular_tecnico") or "sin celular"))
            quien = {"tecnico": "Técnico", "agente": "Asistente", "pem": "Usted"}
            for m in s.get("chat") or []:
                self.chat.insert("end", "%s  %s: " % ((m.get("hora") or "")[11:16], quien.get(m.get("de"), "?")),
                                 m.get("de"))
                self.chat.insert("end", (m.get("texto") or "") + "\n")
            if s.get("para_pem"):
                self.chat.insert("end", "\n⚠ El técnico espera su respuesta (%d mensaje(s)).\n"
                                 % len(s["para_pem"]), "pend")
            if not s.get("chat"):
                self.chat.insert("end", "Sin mensajes todavía.", "agente")
        self.chat.see("end")
        self.chat.config(state="disabled")

    def _enviar_tecnico(self, tipo):
        from . import central_cliente
        s = self._caso()
        texto = self.e_msg.get("1.0", "end").strip()
        if not s:
            self.lbl_envio.config(text="Seleccione la solicitud en la tabla.", fg=P.C["err"])
            return
        if not texto:
            self.lbl_envio.config(text="Escriba el mensaje.", fg=P.C["err"])
            return
        if tipo == "direccionamiento" and not messagebox.askyesno(
                "Direccionamiento final", "Se le enviará al técnico EXACTAMENTE este texto como direccionamiento "
                "final de la solicitud %s:\n\n%s\n\n¿Enviar?" % (s["id"], texto)):
            return
        try:
            r = central_cliente.enviar_mensaje(self.sv.ajustes, s["id"], texto, tipo)
        except ConnectionError as e:
            self.lbl_envio.config(text="No se envió: %s" % e, fg=P.C["err"])
            return
        self.e_msg.delete("1.0", "end")
        self.lbl_envio.config(text="Enviado al técnico." if r.get("whatsapp") else
                              "Registrado (el servidor no tiene WhatsApp configurado).", fg=P.C["ok"])
        self.conexion.cambiar_disponible(self.disponible)      # latir ya para traer la conversacion

    def _alternar_disponible(self):
        self.disponible = not self.disponible
        self.conexion.cambiar_disponible(self.disponible)
        self._pintar_disponible()

    def _pintar_disponible(self):
        if self.disponible:
            self.b_disp.config(text="● Disponible", bg=P.C["ok"], fg="#0d0d0c")
        else:
            self.b_disp.config(text="○ No disponible", bg=P.C["card2"], fg=P.C["txt"])

    def _estado_central(self, est):
        if not self.winfo_exists():
            return
        self.luz_central.config(fg=P.C["ok"] if est.get("ok") else P.C["err"])
        msg = est.get("mensaje", "")
        if est.get("simulacion"):
            msg += "  (servidor en simulación: no asigna)"
        elif est.get("ok") and not est.get("correo_central"):
            msg += "  · el central no lee correo: inicie su Lector de correo abajo"
        import time as _t
        if est.get("nuevos"):                       # la tabla se refresca sola cada 3 s
            self._aviso = ("Nueva solicitud asignada: %s (la plantilla llega con el correo)"
                           % ", ".join(est["nuevos"]), _t.time())
            self.bell()
        elif est.get("plantillas"):
            self._aviso = ("Plantilla lista: %s · ya puede Procesar" % ", ".join(est["plantillas"]), _t.time())
            self.bell()
        elif est.get("preguntas"):
            self._aviso = ("El técnico de la %s escribió: revise abajo y respóndale" % ", ".join(est["preguntas"]),
                           _t.time())
            self.bell()
        aviso = getattr(self, "_aviso", None)
        if est.get("ok") and aviso and _t.time() - aviso[1] < 60:   # el aviso se queda 1 minuto a la vista
            msg = aviso[0]
        self.lbl_central.config(text=msg, fg=P.C["txt"] if est.get("ok") else P.C["err"])

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

    def _tiempo(self, s):
        """Tiempo de gestion desde la asignacion (en vivo si sigue abierta; final si ya se documento)."""
        from . import tiempos
        rec = self.sv.store.cargar(s["id"]) or {}
        base = dict(rec, txt_sol=rec.get("txt_sol") or s["datos"].get("txt_sol", ""),
                    propiedad_red=s["datos"].get("propiedad_red", ""))
        hecha = rec.get("documentada_en") or rec.get("cerrada_en")
        if s["estado"] not in cola.ABIERTOS and not hecha:
            return "—", False
        m = tiempos.medir(base, s)
        return tiempos.texto(m), m["excedido"] and not hecha

    def refrescar(self):
        if not self.winfo_exists():
            return
        if getattr(self, "_tarea", None):            # una sola actualizacion programada (antes se acumulaban)
            try:
                self.after_cancel(self._tarea)
            except Exception:
                pass
        sel = self.t.selection()
        for i in self.t.get_children():
            self.t.delete(i)
        excedidas = []
        for s in reversed(cola.solicitudes()):
            d = s["datos"]
            dem = s.get("demora_correo_s")
            t_txt, excedida = self._tiempo(s)
            if excedida:
                excedidas.append(s["id"])
            self.t.insert("", "end", iid=s["id"], tags=("excedida",) if excedida else (), values=(
                s["id"], d.get("rr", ""), d.get("cliente", ""), s["estado"].replace("_", " "),
                "✓" if s.get("plantilla") else "—", self._hora(d.get("creada") or s.get("recibida")),
                self._hora(s.get("correo_en")), ("%d:%02d" % divmod(dem, 60)) if dem is not None else "—", t_txt))
        if sel and self.t.exists(sel[0]):
            self.t.selection_set(sel[0])
        abiertas = [s for s in cola.solicitudes() if s["estado"] in cola.ABIERTOS]
        from . import tiempos
        self.lbl.config(text="%d abierta(s)" % len(abiertas) + (
            "  ·  ⚠ %s: %s" % (tiempos.ALERTA, ", ".join(excedidas)) if excedidas else ""),
            fg=P.C["err"] if excedidas else P.C["mut"])
        self._auto_procesar()
        self._pintar_chat()
        self._pintar_flujo()
        self._tarea = self.after(3000, self.refrescar)

    def _flujo(self):
        """Un solo boton: abre/cierra el lector de SharePoint y el de correo a la vez."""
        if self.serv.hay_vivos():
            self.serv.detener_todo()
        else:
            self.serv.iniciar_todo(self.serv.var_ver.get())
        self._pintar_flujo()

    def _pintar_flujo(self):
        vivo = self.serv.hay_vivos()
        inicio = "▶  Iniciar flujo (correo)" if getattr(self, "central", False) else "▶  Iniciar flujo (SharePoint + correo)"
        self.b_flujo.config(text="■  Detener flujo" if vivo else inicio,
                            bg=P.C["card2"] if vivo else P.C["acc"], fg=P.C["txt"] if vivo else P.C["on_acc"])

    def iniciar_al_abrir(self):
        if self.central:                           # el servidor central lee SharePoint y el correo
            return
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
        if s["estado"] not in cola.ABIERTOS:
            messagebox.showinfo("Procesar", "La solicitud %s está «%s»: ya no se procesa." % (
                s["id"], s["estado"].replace("_", " ")))
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

    def _liberar(self):
        """Devuelve la solicitud: en SharePoint queda sin PEM y en "Sin Asignar" para que otro la tome.
        El lector no la vuelve a tomar para mi en las proximas horas."""
        s = self._caso()
        if not s:
            return
        if s["estado"] not in cola.ABIERTOS:
            messagebox.showinfo("Liberar", "Solo se puede liberar una solicitud abierta (asignada o en proceso).")
            return
        if getattr(self, "ocupado", None) and self.ocupado() and s["estado"] == "en_proceso":
            messagebox.showinfo("Liberar", "Hay un proceso corriendo con esta solicitud. Espere a que termine o "
                                "cancélelo.")
            return
        nombre = (self.sv.ajustes.get("pem_nombre") or "").strip()
        if not nombre:
            messagebox.showinfo("Liberar", "Escriba su nombre (como en SharePoint) en Ajustes.")
            return
        if not messagebox.askyesno("Liberar solicitud", "La solicitud %s se devolverá: en SharePoint quedará sin "
                                   "PEM y en «Sin Asignar» para que otro PEM la tome.\n\n¿Continuar?" % s["id"]):
            return
        cola.pedir_liberar(s["id"], nombre)
        self.refrescar()
        messagebox.showinfo("Liberar", "Listo. El lector de SharePoint la liberará en su próxima vuelta "
                            "(el flujo debe estar iniciado).")

    def _quitar(self):
        s = self._caso()
        if s and messagebox.askyesno("Quitar", "¿Quitar la solicitud %s de la cola? (No toca SharePoint)" % s["id"]):
            cola.quitar(s["id"])                    # con bloqueo: el lector puede estar escribiendo la cola
            self.refrescar()

    def detener_todo(self):
        self.serv.detener_todo()
        if getattr(self, "conexion", None):
            self.conexion.detener()


# ======================================================================================= EQUIPO
class PanelEquipo(tk.Frame):
    """Quien esta en linea, ausente o desconectado (carpeta compartida del equipo en OneDrive)."""
    COLS = ("PEM", "Estado", "Último uso", "Activo hoy")

    def __init__(self, padre, servicio):
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        _titulo(self, "Equipo", "Quién está usando el optimizador (estado automático, nadie lo puede cambiar a mano). Activo: usó la aplicación en los últimos 5 "
                "minutos o tiene un proceso corriendo. Ausente: la tiene abierta pero lleva 5 minutos sin usarla. "
                "Desconectado: cerró la aplicación o su PC no sincroniza.")
        m, self.t = P._tabla(self, self.COLS, (260, 150, 160, 130), alto=10)
        m.pack(fill="both", expand=True, pady=8)
        self.t.tag_configure("en_linea", foreground=P.C["ok"])
        self.t.tag_configure("ausente", foreground=P.C["warn"])
        self.t.tag_configure("desconectado", foreground=P.C["mut"])
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w",
                            justify="left")
        self.lbl.pack(fill="x")
        P.ad.envolver(self.lbl)
        self._tarea = None
        self.refrescar()

    def refrescar(self):
        from . import presencia
        if not self.winfo_exists():
            return
        if self._tarea:
            try:
                self.after_cancel(self._tarea)
            except Exception:
                pass
        carpeta = (self.sv.ajustes.get("carpeta_equipo") or "").strip()
        for i in self.t.get_children():
            self.t.delete(i)
        if not carpeta:
            self.lbl.config(text="Configure la carpeta compartida del equipo en Ajustes (una carpeta de OneDrive o "
                                 "SharePoint que todos los PEM tengan sincronizada).", fg=P.C["warn"])
        else:
            filas = presencia.equipo(carpeta)
            for f in filas:
                self.t.insert("", "end", tags=(f["estado"],), values=(
                    f["nombre"], presencia.ETIQUETA.get(f["estado"], f["estado"]),
                    presencia.hace(f["ultima_actividad"]),
                    ("%d h %02d min" % divmod(f["en_linea_hoy_min"], 60)) if f["en_linea_hoy_min"] else "—"))
            n = sum(1 for f in filas if f["estado"] == "en_linea")
            self.lbl.config(text="%d activo(s) · %d ausente(s) · %d desconectado(s) · se actualiza cada 30 s" % (
                n, sum(1 for f in filas if f["estado"] == "ausente"),
                sum(1 for f in filas if f["estado"] == "desconectado")) if filas else
                "Nadie ha publicado su estado todavía en esa carpeta.", fg=P.C["mut"])
        self._tarea = self.after(30000, self.refrescar)


# ======================================================================================= ADMIN
class PanelAdmin(tk.Frame):
    """ROL ADMIN: lista de PEM (agregar, activar/desactivar, quitar) y reparto automatico.
    El reparto lo hace el Lector de SharePoint de ESTE PC en cada vuelta (Cola -> Iniciar flujo): misma regla que la
    autoasignacion, solo a PEM activos aqui y Activos en la app (pestana Equipo)."""
    COLS = ("PEM (nombre como en SharePoint)", "Lista del admin", "En la app", "Última asignación")

    def __init__(self, padre, servicio):
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        _titulo(self, "Administrador", "Agregue a cada PEM con su nombre EXACTO de la columna PEM_ASIGNADO y actívelo. "
                "Se reparte la solicitud libre más antigua al PEM activo que esté usando la app y no tenga ninguna "
                "abierta (primero el que lleva más tiempo sin recibir). Mientras usted reparte, los PEM de la lista no "
                "se autoasignan. El reparto lo hace su Lector de SharePoint: deje el flujo iniciado en la Cola.")
        top = P.ad.Flujo(self, P.C["bg"])
        top.pack(fill="x")
        self.e_nuevo = P._entry(top, width=30)
        self.e_nuevo.pack(side="left", ipady=5)
        self.e_nuevo.bind("<Return>", lambda e: self._agregar())
        P.BOTON(top, "Agregar", self._agregar, True, 10).pack(side="left", padx=6)
        P.BOTON(top, "Activar / Desactivar", self._alternar, False, 20).pack(side="left")
        P.BOTON(top, "Quitar", self._quitar, False, 9).pack(side="left", padx=6)
        m, self.t = P._tabla(self, self.COLS, (300, 140, 150, 150), alto=9)
        m.pack(fill="x", pady=8)
        for tag, color in (("on", P.C["ok"]), ("off", P.C["mut"]), ("lejos", P.C["warn"])):
            self.t.tag_configure(tag, foreground=color)
        self.t.bind("<Double-1>", lambda e: self._alternar())
        card = tk.Frame(self, bg=P.C["card"], highlightbackground=P.C["line"], highlightcolor=P.C["line"],
                        highlightthickness=1)
        card.pack(fill="x", pady=(4, 0))
        inner = P.ad.Flujo(card, P.C["card"], hueco=10)
        inner.pack(fill="x", padx=18, pady=12)
        self.repartir = tk.BooleanVar(value=bool(servicio.ajustes.get("admin_repartir")))
        self.simular = tk.BooleanVar(value=bool(servicio.ajustes.get("admin_simular", True)))
        tk.Checkbutton(inner, text="Repartir automáticamente", variable=self.repartir, command=self._guardar,
                       bg=P.C["card"], fg=P.C["acc"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                       font=(P.FONT, 11, "bold"), bd=0, highlightthickness=0).pack(side="left")
        tk.Checkbutton(inner, text="Simulación (solo muestra a quién asignaría)", variable=self.simular,
                       command=self._guardar, bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"],
                       selectcolor=P.C["bg"], font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left")
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w", justify="left")
        self.lbl.pack(fill="x", pady=(6, 0))
        P.ad.envolver(self.lbl)
        self._tarea = None
        self.refrescar()

    def _guardar(self):
        from hac_zac.servicio import guardar_ajustes
        self.sv.ajustes["admin_repartir"] = bool(self.repartir.get())
        self.sv.ajustes["admin_simular"] = bool(self.simular.get())
        guardar_ajustes(self.sv.ajustes)
        self.refrescar()

    def refrescar(self):
        from . import presencia, reparto_equipo
        if not self.winfo_exists():
            return
        if self._tarea:
            try:
                self.after_cancel(self._tarea)
            except Exception:
                pass
        aj = self.sv.ajustes
        carpeta = (aj.get("carpeta_equipo") or "").strip()
        pres = reparto_equipo.presencia_por_nombre(carpeta) if carpeta else {}
        sel = self.t.selection()
        for i in self.t.get_children():
            self.t.delete(i)
        roster = cola.ingenieros()
        for p in roster:
            est = pres.get(cola._plano(p["nombre"]), "")
            tag = "off" if not p.get("activo") else ("on" if est == "en_linea" else "lejos")
            self.t.insert("", "end", iid=p["nombre"], tags=(tag,), values=(
                p["nombre"], "● Activo" if p.get("activo") else "○ Inactivo",
                presencia.ETIQUETA.get(est, "○ Sin dato") if carpeta else "— (sin carpeta)",
                (p.get("ultimo") or "—").replace("T", " ")[5:16]))
        if sel and self.t.exists(sel[0]):
            self.t.selection_set(sel[0])
        listos = [p["nombre"] for p in roster if p.get("activo") and pres.get(cola._plano(p["nombre"])) == "en_linea"]
        if not carpeta:
            msg, color = "Falta la carpeta del equipo en Ajustes: sin ella no se sabe quién está en línea y no se reparte.", P.C["err"]
        elif not self.repartir.get():
            msg, color = "Reparto apagado. Active «Repartir automáticamente».", P.C["mut"]
        elif self.simular.get():
            msg, color = ("SIMULACIÓN: su Lector de SharePoint mostrará en la Cola a quién asignaría, sin escribir. "
                          "Pueden recibir ahora: %s." % (", ".join(listos) or "nadie")), P.C["warn"]
        else:
            cod, minutos, faltan = reparto_equipo.estado_publicacion(carpeta, roster)
            if cod == "sin_archivo":
                msg, color = ("REPARTO DETENIDO: su Lector de SharePoint todavía no ha repartido. Vaya a la Cola y "
                              "pulse ▶ Iniciar flujo; mientras tanto los PEM se autoasignan."), P.C["err"]
            elif cod == "detenido":
                msg, color = ("REPARTO DETENIDO: su Lector de SharePoint no reparte hace %d min, así que los PEM se "
                              "están autoasignando. Vaya a la Cola y pulse ▶ Iniciar flujo." % minutos), P.C["err"]
            else:
                msg, color = ("Repartiendo DE VERDAD (última vuelta hace %d min). Pueden recibir ahora: %s."
                              % (minutos, ", ".join(listos) or "nadie")), P.C["ok"]
                if faltan:
                    msg += " Recién agregados (entran en la próxima vuelta): %s." % ", ".join(faltan)
        self.lbl.config(text=msg, fg=color)
        self._tarea = self.after(30000, self.refrescar)

    def _agregar(self):
        n = " ".join(self.e_nuevo.get().split())
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
        pass                                   # el reparto vive en el Lector de SharePoint (pestana Cola)
