# -*- coding: utf-8 -*-
"""Centro de control: 'Cola' (mis solicitudes + lectores) y 'Admin' (ingenieros + agente administrador)."""
import os
import queue
import tkinter as tk
from tkinter import messagebox, simpledialog

from . import cola, reparto_equipo, turnos
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
            if not confirmar_detener(self, pr.nombre):
                return
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


AVISO_DETENER = ("¿Seguro que quiere detener %s?\n\n"
                 "Si lo detiene:\n"
                 "  •  NO le llegan solicitudes nuevas de SharePoint.\n"
                 "  •  NO se copian las plantillas del correo.\n"
                 "  •  Si es administrador, se DETIENE EL REPARTO del equipo.\n\n"
                 "Lo normal es dejarlo encendido todo el turno.\n\n"
                 "¿Detenerlo de todas formas?")


def confirmar_detener(padre, que="el flujo"):
    """Antes de apagar el flujo (o un lector): advertencia; por defecto queda en «No»."""
    return messagebox.askyesno("Detener el flujo", AVISO_DETENER % (que if que == "el flujo" else "el " + que),
                               icon="warning", default="no", parent=padre.winfo_toplevel())


def _titulo(padre, texto, ayuda):
    tk.Label(padre, text=texto, bg=P.C["bg"], fg=P.C["txt"], font=(P.SERIF, 17, "bold")).pack(anchor="w")
    a = tk.Label(padre, text=ayuda, bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 10), justify="left")
    a.pack(anchor="w", pady=(0, 8))
    P.ad.envolver(a)


# ======================================================================================= COLA
class PanelCola(tk.Frame):
    COLS = ("Solicitud", "Cuenta RR", "Cliente", "Estado", "Plantilla", "SharePoint", "Correo", "Demora", "Tiempo")

    def __init__(self, padre, servicio, procesar, desde_script=False):
        super().__init__(padre, bg=P.C["bg"])
        self.sv, self.procesar = servicio, procesar
        self.desde_script = bool(desde_script)
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
        self._fila_flujo = P.ad.Flujo(self, P.C["bg"], hueco=8)
        self.b_flujo = P.BOTON(self._fila_flujo, "▶  Iniciar flujo (correo)" if self.central else
                               "▶  Iniciar flujo (SharePoint + correo)", self._flujo, True, 34)
        self.b_flujo.pack(side="left")
        # Reiniciar: apaga y vuelve a abrir los lectores (p. ej. para que se apliquen las opciones del navegador)
        self.b_reiniciar = P.BOTON(self._fila_flujo, "↻  Reiniciar flujo", self._reiniciar, False, 18)
        self._reiniciando = False
        if not self.central:                       # con central: SharePoint y correo los atiende el servidor
            self._fila_flujo.pack(fill="x", pady=(0, 8))
            # Cuantas hay en cola en SharePoint (lo deja el lector en cada vuelta, ~6 s; se pinta cada 3 s)
            self.lbl_conteo = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 12, "bold"),
                                       anchor="w", justify="left")
            self.lbl_conteo.pack(fill="x", pady=(0, 8))
            P.ad.envolver(self.lbl_conteo)
        filas =((("correo", "Lector de correo", "correo_lector.py"),) if self.central else
                 (("sp", "Lector de SharePoint", "sp_lector.py"), ("correo", "Lector de correo", "correo_lector.py")))
        self.serv = _Servicios(self, filas, servicio, self._args)
        self.auto_proc = tk.BooleanVar(value=bool(servicio.ajustes.get("auto_procesar", False)))
        tk.Checkbutton(self.serv.opciones, text="Procesar solo cuando llegue la plantilla", variable=self.auto_proc,
                       command=self._guardar_auto, bg=P.C["card"], fg=P.C["acc"], activebackground=P.C["card"],
                       selectcolor=P.C["bg"], font=(P.FONT, 10, "bold"), bd=0,
                       highlightthickness=0).pack(side="left", padx=(12, 0))
        self.al_abrir = tk.BooleanVar(value=bool(desde_script or servicio.ajustes.get("flujo_al_abrir", False)))
        cb = tk.Checkbutton(self.serv.opciones, text="Iniciar el flujo al abrir" + (" (siempre, desde el script)"
                                                                                   if desde_script else ""),
                            variable=self.al_abrir, command=self._guardar_auto, bg=P.C["card"], fg=P.C["mut"],
                            activebackground=P.C["card"], selectcolor=P.C["bg"], font=(P.FONT, 10), bd=0,
                            highlightthickness=0)
        if desde_script:                           # fijo: no se puede cambiar
            cb.config(state="disabled", disabledforeground=P.C["mut"])
        cb.pack(side="left", padx=(12, 0))
        tk.Label(self.serv.opciones, text="Ver navegador:", bg=P.C["card"], fg=P.C["mut"],
                 font=(P.FONT, 10)).pack(side="left", padx=(14, 2))
        self.ver = {}
        for clave, nombre in (("sp", "SharePoint"), ("correo", "Correo"), ("portal", "Portal")):
            v = tk.BooleanVar(value=bool(servicio.ajustes.get("ver_" + clave, True)))
            self.ver[clave] = v
            tk.Checkbutton(self.serv.opciones, text=nombre, variable=v, command=self._cambio_ver,
                           bg=P.C["card"], fg=P.C["txt"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                           font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left", padx=(6, 0))
        self.serv.pack(fill="x")
        b = P.ad.Flujo(self, P.C["bg"])
        b.pack(fill="x", pady=(10, 0))
        P.BOTON(b, "Procesar", self._procesar, True, 11).pack(side="left")
        P.BOTON(b, "Marcar terminada", self._terminar, False, 16).pack(side="left", padx=6)
        P.BOTON(b, "Quitar de la cola", self._quitar, False, 15).pack(side="left")
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
        return ["--nombre", nombre]                 # solo los administradores asignan

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
        self._pintar_conteo()
        self._tarea = self.after(3000, self.refrescar)

    def _pintar_conteo(self):
        if not hasattr(self, "lbl_conteo"):
            return
        c = cola.conteo()
        n = (c or {}).get("libres", 0)
        color = P.C["mut"] if not c else (P.C["err"] if n >= 5 else (P.C["warn"] if n else P.C["ok"]))
        self.lbl_conteo.config(text="📋 " + cola.texto_conteo(c), fg=color)

    def _flujo(self):
        """Un solo boton: abre/cierra el lector de SharePoint y el de correo a la vez. Detener pregunta antes."""
        if getattr(self, "_reiniciando", False):
            return
        if self.serv.hay_vivos():
            if not confirmar_detener(self):
                return
            self.serv.detener_todo()
        else:
            self.serv.iniciar_todo(self.serv.var_ver.get())
        self._pintar_flujo()

    def _pintar_flujo(self):
        vivo = self.serv.hay_vivos()
        inicio = "▶  Iniciar flujo (correo)" if getattr(self, "central", False) else "▶  Iniciar flujo (SharePoint + correo)"
        if getattr(self, "_reiniciando", False):
            self.b_flujo.config(text="↻  Reiniciando…", bg=P.C["card2"], fg=P.C["mut"])
        else:
            self.b_flujo.config(text="■  Detener flujo" if vivo else inicio,
                                bg=P.C["card2"] if vivo else P.C["acc"], fg=P.C["txt"] if vivo else P.C["on_acc"])
        b = getattr(self, "b_reiniciar", None)
        if b is not None:
            if vivo and not self._reiniciando:
                if not b.winfo_manager():
                    b.pack(side="left")
            elif b.winfo_manager():
                b.pack_forget()

    REINICIO_S = 3              # pausa entre apagar y volver a abrir (que Chrome termine de cerrarse)

    def _reiniciar(self, preguntar=True):
        """Apaga y vuelve a abrir los lectores. No usa la alerta de Detener: el flujo vuelve solo en segundos."""
        if self._reiniciando or not self.serv.hay_vivos():
            return
        if preguntar and not messagebox.askyesno(
                "Reiniciar flujo", "Se cierran y se vuelven a abrir los lectores de SharePoint y correo (unos "
                "%d s). Sirve para aplicar las opciones del navegador.\n\n¿Reiniciar ahora?" % (self.REINICIO_S + 6),
                parent=self.winfo_toplevel()):
            return
        self._reiniciando = True
        self.serv.detener_todo()
        self._pintar_flujo()

        def volver():
            self._reiniciando = False
            if not self.serv.hay_vivos():
                self.serv.iniciar_todo(self.serv.var_ver.get())
            self._pintar_flujo()
        self.after(self.REINICIO_S * 1000, volver)

    def iniciar_al_abrir(self):
        """Abierta desde el script: el flujo arranca SIEMPRE (no se puede apagar esa opcion). Desde el centro de
        control, segun la casilla «Iniciar el flujo al abrir»."""
        if self.central:                           # el servidor central lee SharePoint y el correo
            return
        if (self.desde_script or self.al_abrir.get()) and not self.serv.hay_vivos():
            self.serv.iniciar_todo(False)
            self._pintar_flujo()

    def _cambio_ver(self):
        """Cambio «Ver navegador»: se guarda y, si el flujo esta encendido, ofrece reiniciarlo para aplicarlo ya."""
        self._guardar_auto()
        if self.serv.hay_vivos() and not self._reiniciando and messagebox.askyesno(
                "Ver navegador", "Para aplicar el cambio del navegador conviene reiniciar el flujo (unos %d s).\n\n"
                "¿Reiniciarlo ahora?" % (self.REINICIO_S + 6), parent=self.winfo_toplevel()):
            self._reiniciar(preguntar=False)

    def _guardar_auto(self):
        from hac_zac.servicio import guardar_ajustes
        self.sv.ajustes["auto_procesar"] = bool(self.auto_proc.get())
        if not self.desde_script:                  # desde el script es fijo: no se guarda
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
        # al final del turno no arranca sola una que el PEM aun no acepto (la ventana se lo pregunta)
        sin_responder = {x["id"] for x in self._por_aceptar()}
        sig = next((x for x in todas if x["estado"] == "asignada" and x.get("plantilla") and
                    x["id"] not in sin_responder), None)
        if sig:
            self.procesar(sig)

    def _por_aceptar(self):
        try:
            from . import reparto_equipo
            nombre = (self.sv.ajustes.get("pem_nombre") or "").strip()
            carpeta = (self.sv.ajustes.get("carpeta_equipo") or "").strip()
            return cola.por_aceptar(nombre, reparto_equipo.franja_de(carpeta, nombre)) if nombre else []
        except Exception:
            return []

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
        if s["id"] in {x["id"] for x in self._por_aceptar()}:
            cola.marcar_aceptada(s["id"])           # la proceso a mano: la acepto
        self.procesar(s)

    def _terminar(self):
        s = self._caso()
        if s:
            cola.cambiar_estado(s["id"], "terminada")
            self.refrescar()

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
    """Quien esta en proceso, disponible, en pausa, ausente o desconectado (carpeta compartida en OneDrive)."""
    COLS = ("PEM", "Estado", "Turno hoy", "Último uso", "En línea hoy")

    def __init__(self, padre, servicio):
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        _titulo(self, "Equipo", "Quién está trabajando (estado automático, nadie lo cambia a mano). "
                "En proceso: tiene una solicitud abierta (se ve cuál). Disponible: usa la app y no tiene ninguna. "
                "En pausa: se puso en pausa (almuerzo, reunión...) y no recibe solicitudes. Ausente: la app abierta "
                "pero 5 minutos sin usarla. Fuera de turno: no es su horario (el turno que eligió al abrir). Horas extra: las que el PEM pidió con «⏱ Horas extra» (recibe solicitudes). "
                "Desconectado: cerró la aplicación o su PC no sincroniza.")
        m, self.t = P._tabla(self, self.COLS, (220, 300, 160, 130, 100), alto=10)
        m.pack(fill="both", expand=True, pady=8)
        self.t.tag_configure("en_proceso", foreground=P.C["acc"])
        self.t.tag_configure("disponible", foreground=P.C["ok"])
        self.t.tag_configure("cierre", foreground=P.C["ok"])
        self.t.tag_configure("extra", foreground=P.C["acc"])
        self.t.tag_configure("fuera_turno", foreground=P.C["mut"])
        self.t.tag_configure("ausente", foreground=P.C["warn"])
        self.t.tag_configure("pausa", foreground=P.C["warn"])
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
            franjas = {cola._plano(p["nombre"]): p.get("franja") or "" for p in reparto_equipo.roster(carpeta)}
            orden = {"en_proceso": 0, "disponible": 1, "extra": 1, "cierre": 2, "pausa": 3, "ausente": 4,
                     "fuera_turno": 5, "desconectado": 6}
            vistas = []
            for f in filas:
                fr = franjas.get(cola._plano(f["nombre"]), "")
                vistas.append((presencia.situacion(f["estado"], f.get("caso"), f.get("pausa"), turnos.situacion(fr),
                                                   f.get("extra")), fr, f))
            vistas.sort(key=lambda x: (orden.get(x[0][0], 9), x[2]["nombre"].lower()))
            cuenta = {}
            for (clave, texto), fr, f in vistas:
                cuenta[clave] = cuenta.get(clave, 0) + 1
                self.t.insert("", "end", tags=(clave,), values=(
                    f["nombre"], texto, turnos.texto(fr) or "—", presencia.hace(f["ultima_actividad"]),
                    ("%d h %02d min" % divmod(f["en_linea_hoy_min"], 60)) if f["en_linea_hoy_min"] else "—"))
            disp = cuenta.get("disponible", 0) + cuenta.get("cierre", 0) + cuenta.get("extra", 0)
            self.lbl.config(text="%d en proceso · %d disponible(s) · %d en pausa · %d ausente(s) · %d fuera de turno · "
                                 "%d desconectado(s) · se actualiza cada 30 s" % (
                                     cuenta.get("en_proceso", 0), disp, cuenta.get("pausa", 0),
                                     cuenta.get("ausente", 0), cuenta.get("fuera_turno", 0),
                                     cuenta.get("desconectado", 0))
                            if filas else "Nadie ha publicado su estado todavía en esa carpeta.", fg=P.C["mut"])
        self._tarea = self.after(30000, self.refrescar)


# ======================================================================================= ADMIN
class PanelAdmin(tk.Frame):
    """ROL ADMIN: lista de PEM COMPARTIDA (carpeta del equipo: agregar, activar/desactivar, franja de turno, quitar),
    reparto automatico y reasignar. El reparto lo hace el Lector de SharePoint de este PC (Cola -> Iniciar flujo).
    Con varios admin reparte uno; si se detiene, otro admin conectado lo toma solo."""
    COLS = ("PEM (nombre como en SharePoint)", "Lista", "Franja", "Turno hoy", "En la app", "Última asignación")

    def __init__(self, padre, servicio):
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        _titulo(self, "Administrador", "Agregue a cada PEM con su nombre EXACTO de PEM_ASIGNADO, actívelo y póngale su "
                "franja de la semana (Temprano A/B, Medio C/D, Tarde E/F; el sábado usa B, D y F). Recibe la solicitud "
                "libre más antigua el PEM activo, EN TURNO, usando la app y sin ninguna abierta; deja de recibir 1 min "
                "antes de su salida. Con varios admin reparte uno y, si se detiene, otro lo toma solo.")
        top = P.ad.Flujo(self, P.C["bg"])
        top.pack(fill="x")
        self.e_nuevo = P._entry(top, width=30)
        self.e_nuevo.pack(side="left", ipady=5)
        self.e_nuevo.bind("<Return>", lambda e: self._agregar())
        P.BOTON(top, "Agregar", self._agregar, True, 10).pack(side="left", padx=6)
        P.BOTON(top, "Activar / Desactivar", self._alternar, False, 20).pack(side="left")
        P.BOTON(top, "Quitar", self._quitar, False, 9).pack(side="left", padx=6)
        fr = P.ad.Flujo(self, P.C["bg"], hueco=6)
        fr.pack(fill="x", pady=(6, 0))
        tk.Label(fr, text="Franja de la semana:", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9, "bold")).pack(side="left")
        for clave in ("temprano", "medio", "tarde", ""):
            P.BOTON(fr, turnos.NOMBRE_FRANJA[clave], lambda c=clave: self._franja(c), False, 11).pack(side="left")
        P.BOTON(fr, "Reasignar solicitud…", self._reasignar, False, 20).pack(side="left", padx=(12, 0))
        m, self.t = P._tabla(self, self.COLS, (230, 90, 90, 150, 250, 110), alto=9)
        m.pack(fill="x", pady=8)
        for tag, color in (("on", P.C["ok"]), ("off", P.C["mut"]), ("lejos", P.C["warn"]), ("huerfana", P.C["err"])):
            self.t.tag_configure(tag, foreground=color)
        self.t.bind("<Double-1>", lambda e: self._alternar())
        card = tk.Frame(self, bg=P.C["card"], highlightbackground=P.C["line"], highlightcolor=P.C["line"],
                        highlightthickness=1)
        card.pack(fill="x", pady=(4, 0))
        inner = P.ad.Flujo(card, P.C["card"], hueco=10)
        inner.pack(fill="x", padx=18, pady=12)
        self.repartir = tk.BooleanVar(value=bool(servicio.ajustes.get("admin_repartir")))
        self.simular = tk.BooleanVar(value=bool(servicio.ajustes.get("admin_simular", True)))
        self.respaldo = tk.BooleanVar(value=bool(servicio.ajustes.get("admin_respaldo", True)))
        tk.Checkbutton(inner, text="Repartir automáticamente", variable=self.repartir, command=self._guardar,
                       bg=P.C["card"], fg=P.C["acc"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                       font=(P.FONT, 11, "bold"), bd=0, highlightthickness=0).pack(side="left")
        tk.Checkbutton(inner, text="Simulación (solo muestra a quién asignaría)", variable=self.simular,
                       command=self._guardar, bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"],
                       selectcolor=P.C["bg"], font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left")
        tk.Checkbutton(inner, text="Respaldo: si ningún admin reparte en %d min, los PEM en turno se autoasignan"
                       % reparto_equipo.RESPALDO_MIN, variable=self.respaldo, command=self._guardar,
                       bg=P.C["card"], fg=P.C["mut"], activebackground=P.C["card"], selectcolor=P.C["bg"],
                       font=(P.FONT, 10), bd=0, highlightthickness=0).pack(side="left")
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w", justify="left")
        self.lbl.pack(fill="x", pady=(6, 0))
        P.ad.envolver(self.lbl)
        self._tarea = None
        self._casos = {}
        self.refrescar()

    def _carpeta(self):
        return (self.sv.ajustes.get("carpeta_equipo") or "").strip()

    def _guardar(self):
        from hac_zac.servicio import guardar_ajustes
        self.sv.ajustes["admin_repartir"] = bool(self.repartir.get())
        self.sv.ajustes["admin_simular"] = bool(self.simular.get())
        self.sv.ajustes["admin_respaldo"] = bool(self.respaldo.get())
        guardar_ajustes(self.sv.ajustes)
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
        carpeta = self._carpeta()
        filas_eq = {cola._plano(r["nombre"]): r for r in presencia.equipo(carpeta)} if carpeta else {}
        sel = self.t.selection()
        for i in self.t.get_children():
            self.t.delete(i)
        roster = reparto_equipo.roster(carpeta)
        self._casos, listos, huerfanas = {}, [], []
        for p in roster:
            fila = filas_eq.get(cola._plano(p["nombre"])) or {}
            est = fila.get("estado", "")
            sit_t = turnos.situacion(p.get("franja"))
            caso = fila.get("caso") or ""
            if caso:
                self._casos[p["nombre"]] = caso
            # fuera de turno con una abierta NO es huerfana: la termina (horas extra). Solo si se desconecto.
            huerfana = bool(caso) and est == "desconectado"
            if huerfana:
                huerfanas.append("%s (%s)" % (p["nombre"], caso))
            if not carpeta:
                en_app = "— (sin carpeta)"
            elif fila:
                en_app = presencia.situacion(est, caso, fila.get("pausa"), sit_t, fila.get("extra"))[1]
                if huerfana:
                    en_app = "⚠ " + en_app + " · reasignar"
            else:
                en_app = "○ Sin dato"
            from . import horas_extra
            puede = p.get("activo") and est == "en_linea" and (turnos.puede_recibir(p.get("franja")) or
                                                               horas_extra.recibe(fila.get("extra")))
            if puede:
                listos.append(p["nombre"])
            tag = "huerfana" if huerfana else ("off" if not p.get("activo") else ("on" if puede else "lejos"))
            hoy = turnos.texto(p.get("franja")) or "—"
            if sit_t in ("antes", "fuera"):
                hoy += " · fuera"
            elif sit_t == "corte":
                hoy += " · cierre"
            self.t.insert("", "end", iid=p["nombre"], tags=(tag,), values=(
                p["nombre"], "● Activo" if p.get("activo") else "○ Inactivo",
                turnos.NOMBRE_FRANJA.get(p.get("franja") or "", "Sin franja"), hoy, en_app,
                p["ultimo"].replace("T", " ")[5:16] if p.get("ultimo") else "—"))
        if sel and self.t.exists(sel[0]):
            self.t.selection_set(sel[0])
        msg, color = self._estado_reparto(carpeta, roster, listos)
        if huerfanas:
            msg += "  ⚠ Con solicitud abierta y desconectado: %s. Selecciónelo y pulse «Reasignar»." \
                   % ", ".join(huerfanas)
            color = P.C["err"]
        self.lbl.config(text=msg, fg=color)
        self._tarea = self.after(30000, self.refrescar)

    def _estado_reparto(self, carpeta, roster, listos):
        yo = self.sv.ajustes.get("pem_nombre", "")
        recibir = ", ".join(listos) or "nadie"
        if not carpeta:
            return ("Falta la carpeta del equipo en Ajustes: sin ella no se sabe quién está en línea y no se reparte.",
                    P.C["err"])
        otro, s = reparto_equipo.quien_reparte(carpeta)
        lo_hace_otro = otro and not reparto_equipo.mismo(otro, yo) and s is not None and s <= reparto_equipo.LIDER_S
        if not self.repartir.get():
            if lo_hace_otro:
                return "Reparte %s (hace %d s). Pueden recibir ahora: %s." % (otro, s, recibir), P.C["ok"]
            return "Reparto apagado. Active «Repartir automáticamente».", P.C["mut"]
        if self.simular.get():
            return ("SIMULACIÓN: su Lector de SharePoint mostrará en la Cola a quién asignaría, sin escribir. "
                    "Pueden recibir ahora: %s." % recibir), P.C["warn"]
        if lo_hace_otro:
            return ("Reparte %s (hace %d s). Usted queda de RESPALDO: si deja de repartir %d s, su app toma el reparto "
                    "sola. Pueden recibir ahora: %s." % (otro, s, reparto_equipo.LIDER_S, recibir)), P.C["ok"]
        cod, minutos, faltan = reparto_equipo.estado_publicacion(carpeta, roster)
        if cod in ("sin_archivo", "detenido"):
            extra = (" Mientras tanto los PEM en turno se autoasignan (respaldo)." if self.respaldo.get() else
                     " Mientras tanto nadie recibe solicitudes.")
            base = ("todavía no ha repartido" if cod == "sin_archivo" else "no reparte hace %d min" % minutos)
            return ("REPARTO DETENIDO: su Lector de SharePoint %s. Vaya a la Cola y pulse ▶ Iniciar flujo.%s"
                    % (base, extra)), P.C["err"]
        msg = "Repartiendo DE VERDAD (última vuelta hace %d min). Pueden recibir ahora: %s." % (minutos, recibir)
        if faltan:
            msg += " Recién agregados (entran en la próxima vuelta): %s." % ", ".join(faltan)
        return msg, P.C["ok"]

    def _sel(self):
        sel = self.t.selection()
        return sel[0] if sel else None

    def _agregar(self):
        n = " ".join(self.e_nuevo.get().split())
        if n:
            reparto_equipo.agregar(self._carpeta(), n)
            self.e_nuevo.delete(0, "end")
            self.refrescar()

    def _alternar(self):
        n = self._sel()
        if n:
            actual = next((i for i in reparto_equipo.roster(self._carpeta()) if i["nombre"] == n), {})
            reparto_equipo.poner_activo(self._carpeta(), n, not actual.get("activo"))
            self.refrescar()

    def _franja(self, franja):
        n = self._sel()
        if not n:
            messagebox.showinfo("Franja", "Seleccione un PEM de la lista.", parent=self)
            return
        reparto_equipo.poner_franja(self._carpeta(), n, franja)
        self.refrescar()

    def _quitar(self):
        n = self._sel()
        if n and messagebox.askyesno("Quitar", "¿Quitar a %s de la lista?" % n, parent=self):
            reparto_equipo.quitar(self._carpeta(), n)
            self.refrescar()

    def _reasignar(self):
        """Pasa la solicitud abierta del PEM seleccionado a otro PEM activo (la escribe su Lector de SharePoint)."""
        de = self._sel()
        if not de:
            messagebox.showinfo("Reasignar", "Seleccione al PEM que tiene la solicitud.", parent=self)
            return
        caso = self._casos.get(de) or simpledialog.askstring(
            "Reasignar", "%s no publica una solicitud abierta.\nEscriba el ID de la solicitud a reasignar:" % de,
            parent=self)
        if not caso or not str(caso).strip().isdigit():
            return
        otros = [p["nombre"] for p in reparto_equipo.roster(self._carpeta())
                 if p.get("activo") and p["nombre"] != de]
        if not otros:
            messagebox.showinfo("Reasignar", "No hay otro PEM activo en la lista.", parent=self)
            return
        a = _elegir(self, "Reasignar la %s" % caso, "¿A quién se la pasa? (la de %s)" % de, otros)
        if not a:
            return
        if not messagebox.askyesno("Reasignar", "¿Pasar la solicitud %s de %s a %s?\nQueda una nota en "
                                   "Observaciones." % (caso, de, a), parent=self):
            return
        cola.pedir_reasignar(str(caso).strip(), de, a, self.sv.ajustes.get("pem_nombre", "") or "admin")
        messagebox.showinfo("Reasignar", "Pedido. Su Lector de SharePoint la reasigna en la próxima vuelta "
                            "(debe tener el flujo iniciado en la Cola).", parent=self)

    def detener_todo(self):
        pass                                   # el reparto vive en el Lector de SharePoint (pestana Cola)


def _elegir(padre, titulo, texto, opciones):
    """Ventana con una lista para elegir una opcion. Devuelve la elegida o None."""
    v = tk.Toplevel(padre)
    v.title(titulo)
    v.configure(bg=P.C["bg"])
    v.transient(padre.winfo_toplevel())
    tk.Label(v, text=texto, bg=P.C["bg"], fg=P.C["txt"], font=(P.FONT, 10, "bold"), anchor="w").pack(
        fill="x", padx=18, pady=(14, 6))
    lb = tk.Listbox(v, height=min(10, len(opciones)), bg=P.C["card2"], fg=P.C["txt"], relief="flat",
                    selectbackground=P.C["acc"], font=(P.FONT, 10), exportselection=False)
    for o in opciones:
        lb.insert("end", o)
    lb.pack(fill="both", expand=True, padx=18)
    lb.selection_set(0)
    res = {"v": None}

    def ok(e=None):
        s = lb.curselection()
        res["v"] = opciones[s[0]] if s else None
        v.destroy()

    b = P.ad.Flujo(v, P.C["bg"])
    b.pack(fill="x", padx=18, pady=12)
    P.BOTON(b, "Elegir", ok, True, 10).pack(side="left")
    P.BOTON(b, "Cancelar", v.destroy, False, 10).pack(side="left", padx=6)
    lb.bind("<Double-1>", ok)
    v.update_idletasks()
    v.minsize(min(P.ad.px(360), v.winfo_screenwidth() - 40), v.winfo_reqheight())
    v.grab_set()
    v.wait_window()
    return res["v"]


# ======================================================================================= REPORTES (admin)
class PanelReportes(tk.Frame):
    """ROL ADMIN: resumen del dia por PEM desde los reportes de la carpeta del equipo (OneDrive).
    Los archivos completos (pausas, conexion, solicitudes) se abren en Excel con 'Abrir carpeta'."""
    COLS = ("PEM", "Cerradas", "Exitosas", "No exitosas", "Escalam.", "Prom. min", "Superaron",
            "Activo (min)", "Ausente (min)", "En pausa (min)", "Pausas", "Horas extra (día)", "Horas extra (mes)")

    def __init__(self, padre, servicio):
        from datetime import date
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        self.dia = date.today()
        _titulo(self, "Reportes", "Resumen del día por PEM. Cada app deja su registro en la carpeta del equipo "
                "(carpeta «reportes» → una carpeta por PEM → una por mes: Solicitudes, Pausas, Conexion y Horas extra .csv), que abre en Excel. Las solicitudes "
                "se registran al cerrarse (Forms o SharePoint); la conexión, cada vez que cambia el estado.")
        top = P.ad.Flujo(self, P.C["bg"], hueco=6)
        top.pack(fill="x")
        P.BOTON(top, "◀ Día anterior", lambda: self._mover(-1), False, 14).pack(side="left")
        self.lbl_dia = tk.Label(top, text="", bg=P.C["bg"], fg=P.C["txt"], font=(P.FONT, 11, "bold"), padx=8)
        self.lbl_dia.pack(side="left")
        P.BOTON(top, "Día siguiente ▶", lambda: self._mover(1), False, 14).pack(side="left")
        P.BOTON(top, "Hoy", self._hoy, False, 6).pack(side="left")
        P.BOTON(top, "Abrir carpeta de reportes", self._abrir, True, 24).pack(side="left")
        m, self.t = P._tabla(self, self.COLS, (200, 75, 75, 85, 75, 80, 80, 90, 95, 105, 65, 120, 125), alto=10)
        m.pack(fill="both", expand=True, pady=8)
        self.t.tag_configure("alerta", foreground=P.C["warn"])
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(P.FONT, 9), anchor="w",
                            justify="left")
        self.lbl.pack(fill="x")
        P.ad.envolver(self.lbl)
        self._tarea = None
        self.refrescar()

    def _mover(self, dias):
        from datetime import timedelta
        self.dia += timedelta(days=dias)
        self.refrescar()

    def _hoy(self):
        from datetime import date
        self.dia = date.today()
        self.refrescar()

    def _carpeta(self):
        return (self.sv.ajustes.get("carpeta_equipo") or "").strip()

    def _abrir(self):
        from . import reportes
        c = self._carpeta()
        if not c:
            messagebox.showinfo("Reportes", "Configure la carpeta del equipo en Ajustes.", parent=self)
            return
        os.makedirs(reportes.carpeta(c), exist_ok=True)
        os.startfile(reportes.carpeta(c))

    def refrescar(self):
        from . import reportes
        if not self.winfo_exists():
            return
        if self._tarea:
            try:
                self.after_cancel(self._tarea)
            except Exception:
                pass
        self.lbl_dia.config(text=self.dia.strftime("%d/%m/%Y"))
        for i in self.t.get_children():
            self.t.delete(i)
        c = self._carpeta()
        if not c:
            self.lbl.config(text="Configure la carpeta del equipo en Ajustes.", fg=P.C["warn"])
        else:
            res = reportes.resumen_dia(c, self.dia)
            mes = reportes.extra_mes(c, self.dia)
            ent = lambda v: ("%d" % round(v)) if v else "—"
            for nombre in sorted(res, key=str.lower):
                x = res[nombre]
                self.t.insert("", "end", tags=("alerta",) if x["superaron"] else (), values=(
                    nombre, x["cerradas"], x["exitosas"], x["no_exitosas"], x["escalamientos"],
                    ("%.1f" % x["promedio"]).replace(".", ",") if x["promedio"] else "—", x["superaron"],
                    ent(x["activo"]), ent(x["ausente"]), ent(x["pausa"]), x["pausas"],
                    reportes.h_min(x["extra"]), reportes.h_min(mes.get(nombre, 0))))
            tot = sum(x["cerradas"] for x in res.values())
            sup = sum(x["superaron"] for x in res.values())
            ext = sum(x["extra"] for x in res.values())
            self.lbl.config(text=("%d solicitud(es) cerradas · %d superaron el tiempo · %s de horas extra · %d PEM "
                                  "con registro. Detalle: reportes/<PEM>/<mes>/Horas extra.csv. Se actualiza "
                                  "cada minuto." % (tot, sup, reportes.h_min(ext), len(res))) if res else
                            "Sin registros ese día.", fg=P.C["mut"])
        self._tarea = self.after(60000, self.refrescar)

    def detener_todo(self):
        pass
