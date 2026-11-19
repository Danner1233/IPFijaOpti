# -*- coding: utf-8 -*-
"""Pestana Contingencia: Guia de emergencia (proceso manual paso a paso) y Buscador de IPs por nodo (Excel)."""
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from . import buscador_ips as B
from . import panel as P

FONT, ad = P.FONT, P.ad
MONO = ("Consolas", 10)


# ======================================================================================= GUIA DE EMERGENCIA
# (titulo, [lineas]); una linea que empieza con "$ " es un COMANDO (se muestra en otra letra, para copiar).
GUIA = [
    ("Cuándo usar esta guía", [
        "Si el automatismo (script de SecureCRT, lectores o la app) no funciona, la solicitud se hace a mano siguiendo "
        "los mismos pasos que hace el script. Avise al administrador del turno antes de empezar.",
        "Los valores entre < > se reemplazan por los de la solicitud (sin los signos).",
    ]),
    ("1. Tomar la solicitud (SharePoint)", [
        "Lista «Asignar PEM» (Seguimiento Expertos y Estándar – Solicitud IP Fija FTTx Campo).",
        "Solo asigna el administrador. Si le indica tomarla a mano: escriba su nombre en PEM_ASIGNADO y deje "
        "Est_Seg en «Asignada». Revise antes que PEM_ASIGNADO esté vacío (si ya tiene nombre, es de otro PEM).",
        "Desde la asignación corre el tiempo: red Claro 15 min · redes neutras (ATP / ONNET) 30 min.",
    ]),
    ("2. Plantilla (Outlook)", [
        "En Outlook busque la CUENTA RR (solo dígitos, sin puntos). Abra el correo y confirme que el SOLICITUD ID "
        "sea el de la solicitud: puede haber varios correos de la misma cuenta.",
        "Copie la plantilla completa; ahí están serial o MAC, velocidad, Bridge (SI/NO), PROPIEDAD RED y el técnico.",
    ]),
    ("3. Datos de la ONT (Support Portal)", [
        "Consulte por SERIAL o por MAC. Anote: IP de la ONT, SN, nombre del cliente y cuenta RR.",
        "Descripción que se pone en el equipo: NOMBRE_DEL_CLIENTE en mayúsculas, espacios por «_», más «_» y la RR. "
        "Ejemplo: JUAN_PEREZ_GOMEZ_12345678",
    ]),
    ("4. Entrar al jump host (Hendrix)", [
        "SecureCRT → sesión del jump host (HENDRIX_DEMIMASTER, 172.31.238.6) con su usuario de red.",
        "Si el Hendrix no responde: no se puede consultar ni configurar equipos. Use el «Buscador de IPs por nodo» "
        "(pestaña Contingencia → Buscador de IPs por nodo) para ubicar la puerta de enlace y las IPs ya usadas en el nodo, y escale según el procedimiento.",
    ]),
    ("5. Capa 3 por BGP (A9KTRIARA2)", [
        "$ ssh A9KTRIARA2",
        "$ sho bgp vpnv4 unicast rd 100:15604 <IP_ONT>",
        "Busque la línea «X.X.X.X (metric N) from Y.Y.Y.Y (X.X.X.X)»: la primera IP es la del CAPA 3.",
        "$ exit",
    ]),
    ("6. Interfaz, Capa 2 y puerta de enlace (Capa 3)", [
        "$ ssh <IP_CAPA3>",
        "$ screen-length 0 temporary",
        "$ display ip routing-table vpn-instance PROVISION_NACIONAL_HPE <IP_ONT>",
        "Tome la interfaz de la ruta y cambie su sub-interfaz a .201 (ej.: Eth-Trunk10.2010 → Eth-Trunk10.201).",
        "$ dis cur int <INTERFAZ.201>",
        "En «description» está el nombre del CAPA 2 (HAC / ZAC / OH / ATP / ONNET). En «ip address» están la puerta de "
        "enlace y la máscara. Copie ese bloque para la plantilla.",
    ]),
    ("7. IPs libres", [
        "$ dis arp int <INTERFAZ.201> | in I",
        "Las IPs en estado «Incomplete» están libres. Elija una y anótela en la plantilla con su puerta de enlace y "
        "máscara.",
        "Sin Hendrix: «Buscador de IPs por nodo» muestra la puerta de enlace del nodo y las IPs que ya se asignaron "
        "(no las repita). Confírmela apenas vuelva el acceso.",
    ]),
    ("8. Red ATP u ONNET (PROPIEDAD RED)", [
        "Solo se consultan las IPs disponibles (pasos 5 a 7). NO se entra al Capa 2 ni se configura nada.",
    ]),
    ("9. Configurar HAC (Huawei)", [
        "La IP del Capa 2 está en la pestaña «IP Capa 2» de la app (o en historial_capa2.json).",
        "$ ssh <IP_CAPA2>",
        "$ enable",
        "$ display ont info by-sn <SN>",
        "Anote F/S/P (ej. 0/2/5) y ONT-ID.",
        "$ display service-port port <F/S/P> ont <ONT-ID>",
        "Anote el SERVICE-PORT de la VLAN 201.",
        "$ display traffic table ip from-index 0 | no-more",
        "Busque los índices (TID) de INTERNET-BA-IP-<VEL>M-DOWN y INTERNET-BA-IP-<VEL>M-UP.",
        "$ config",
        "$ service-port <SP> outbound traffic-table index <TID_DOWN> inbound traffic-table index <TID_UP>",
        "$ service-port desc <SP> description <NOMBRE_RR>",
        "$ display service-port <SP>",
        "Verifique RX = TID_DOWN, TX = TID_UP y los nombres INTERNET-BA-IP-<VEL>M-DOWN / -UP.",
        "Solo si Bridge = SI (F/S/P = F/S/P → frame/slot/puerto):",
        "$ interface gpon <F>/<S>",
        "$ display ont port attribute <P> <ONT-ID> eth",
        "$ ont port native-vlan <P> <ONT-ID> eth 4 vlan 201",
        "$ display ont port attribute <P> <ONT-ID> eth",
        "$ quit",
        "Para salir del HAC: quit, q y responder y.",
    ]),
    ("10. Configurar ZAC (ZTE)", [
        "$ ssh <IP_CAPA2>",
        "$ sh gpon onu by sn <SN>",
        "Sale algo como gpon_onu-1/2/15:18 → GPON = 1/2/15, ONU = 18 → VPORT = 1/2/15.18:1",
        "$ sh running-config-interface vport-<VPORT>",
        "$ conf t",
        "$ interface vport-<VPORT>",
        "$ service-port 5 user-vlan 201 vlan 201 ingress INTERNET-BA-IP-<VEL>M-UP egress INTERNET-BA-IP-<VEL>M-DOWN",
        "Solo si Bridge = SI:",
        "$ security max-mac-learn 5",
        "$ exit",
        "$ exit",
        "Solo si Bridge = SI:",
        "$ conf t",
        "$ pon-onu-mng gpon_onu-<GPON>:<ONU>",
        "$ vlan port eth_0/4 mode hybrid def-vlan 201",
        "$ exit",
        "$ exit",
        "Nombre y descripción de la ONT:",
        "$ conf t",
        "$ interface gpon_onu-<GPON>:<ONU>",
        "$ name <NOMBRE_RR>",
        "$ description <NOMBRE_RR>",
        "$ exit",
        "$ exit",
        "$ sh running-config-interface gpon_onu-<GPON>:<ONU>",
        "$ sh running-config-interface vport-<VPORT>",
        "Para salir del ZAC: q y q.",
    ]),
    ("11. Verificar", [
        "Vuelva al Capa 3 y repita «dis arp int <INTERFAZ.201> | in I» para confirmar la IP entregada.",
        "Pídale al técnico que pruebe navegación con la IP fija.",
    ]),
    ("12. Cerrar la solicitud", [
        "Exitosa: documente en Microsoft Forms con la plantilla y deje Est_Seg = «Exitosa» en SharePoint.",
        "No exitosa o Escalamiento: NO va a Forms. En SharePoint ponga Est_Seg, la causa (columna «Causa No Exitosa» o "
        "«Causa Escalamiento») y agregue su observación al final de «Observaciones» con fecha y su nombre.",
        "Si se pasó del tiempo (Claro 15 / neutras 30 min): deje la justificación (fotos, observación o «Demora por "
        "parte del PEM»).",
        "Avise al administrador para que la tenga en cuenta en el reparto.",
    ]),
]


# ======================================================================================= BUSCADOR DE IPS
class BuscadorIPs(tk.Frame):
    """Buscar por NODO: puertas de enlace usadas en solicitudes Exitosas y las IPs que ya se asignaron."""
    COLS = ("Nodo", "Puerta de enlace", "Usos", "Última vez", "Red", "OLT", "VLAN")

    def __init__(self, padre, servicio):
        super().__init__(padre, bg=P.C["bg"])
        self.sv = servicio
        ayuda = tk.Label(self, text="Para cuando el Hendrix no responde. Escriba el NODO de la solicitud: salen las "
                         "puertas de enlace usadas en ese nodo (solicitudes Exitosas) y, al elegir una, las IPs que ya "
                         "se asignaron ahí (no las repita). Confirme siempre la IP antes de entregarla.",
                         bg=P.C["bg"], fg=P.C["mut"], font=(FONT, 9), anchor="w", justify="left")
        ayuda.pack(fill="x", pady=(0, 8))
        ad.envolver(ayuda)
        fila = ad.Flujo(self, P.C["bg"], hueco=6)
        fila.pack(fill="x")
        self.e = P._entry(fila, width=24)
        self.e.pack(side="left", ipady=5)
        self.e.bind("<Return>", lambda e: self.buscar())
        P.BOTON(fila, "Buscar", self.buscar, True, 10).pack(side="left")
        P.BOTON(fila, "Actualizar Excel…", self.actualizar, False, 18).pack(side="left", padx=(12, 0))
        m, self.t = P._tabla(self, self.COLS, (110, 150, 60, 100, 110, 200, 70), alto=10)
        m.pack(fill="x", pady=8)
        self.t.bind("<<TreeviewSelect>>", lambda e: self._mostrar_ips())
        tk.Label(self, text="IPs ya asignadas en esa puerta de enlace (selecciónelas y copie con Ctrl+C):",
                 bg=P.C["bg"], fg=P.C["mut"], font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        self.ips = tk.Text(self, height=5, bg=P.C["card2"], fg=P.C["txt"], insertbackground=P.C["txt"],
                           relief="flat", font=MONO, wrap="word")
        self.ips.pack(fill="x", pady=(4, 6))
        self.lbl = tk.Label(self, text="", bg=P.C["bg"], fg=P.C["mut"], font=(FONT, 9), anchor="w", justify="left")
        self.lbl.pack(fill="x")
        ad.envolver(self.lbl)
        self._filas = {}
        self.indice = {}
        self.refrescar()

    def _carpeta(self):
        return (self.sv.ajustes.get("carpeta_equipo") or "").strip() if self.sv else ""

    def refrescar(self, nodo=""):
        """Recarga los datos (otro PEM pudo actualizar el Excel) y, si se da, busca ese nodo."""
        self.indice = B.cargar(self._carpeta())
        if nodo and not self.e.get().strip():
            self.e.insert(0, nodo)
        if self.e.get().strip():
            self.buscar()
        else:
            self._pie()

    def _pie(self, extra=""):
        i = self.indice
        if not i:
            self.lbl.config(text="Todavía no hay datos: pulse «Actualizar Excel…» y elija el Excel «Buscador IPs "
                                 "por Nodo».", fg=P.C["warn"])
            return
        cuando = (i.get("importado") or "").replace("T", " ")[:16]
        self.lbl.config(text=("%sDatos del Excel «%s» cargado el %s · %d nodos · %d solicitudes exitosas. "
                              "Compartido con el equipo por la carpeta del equipo." % (
                                  extra, i.get("origen", ""), cuando, len(i.get("nodos") or {}),
                                  i.get("exitosas", 0))), fg=P.C["mut"])

    def buscar(self):
        for x in self.t.get_children():
            self.t.delete(x)
        self.ips.delete("1.0", "end")
        self._filas = {}
        res = B.buscar(self.indice, self.e.get())
        for k, r in enumerate(res):
            iid = str(k)
            self._filas[iid] = r
            self.t.insert("", "end", iid=iid, values=(r["nodo"], r["gw"], r["n"], r["ultima"] or "—", r["red"] or "—",
                                                      r["olt"] or "—", r["vlan"] or "—"))
        if res:
            self.t.selection_set("0")
            self._pie("%d puerta(s) de enlace. " % len(res))
        elif self.indice and self.e.get().strip():
            self._pie("Sin resultados para «%s». " % self.e.get().strip())
        else:
            self._pie()

    def _mostrar_ips(self):
        sel = self.t.selection()
        self.ips.delete("1.0", "end")
        if sel and sel[0] in self._filas:
            r = self._filas[sel[0]]
            self.ips.insert("1.0", ", ".join(r["ips"]) if r["ips"] else "(sin IPs registradas)")

    def actualizar(self):
        ruta = filedialog.askopenfilename(parent=self.winfo_toplevel(),
                                          title="Excel «Buscador IPs por Nodo» actualizado",
                                          filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")])
        if not ruta:
            return
        self.lbl.config(text="Leyendo el Excel… (puede tardar un minuto)", fg=P.C["acc"])
        carpeta = self._carpeta()

        def trabajo():
            try:
                ind = B.importar(ruta, carpeta, progreso=lambda n: self.after(
                    0, lambda: self.lbl.config(text="Leyendo el Excel… %d filas" % n)))
                self.after(0, lambda: self._listo(ind))
            except Exception as e:
                self.after(0, lambda: (self.lbl.config(text="No se pudo actualizar: %s" % e, fg=P.C["err"]),
                                       messagebox.showerror("Actualizar Excel", str(e),
                                                            parent=self.winfo_toplevel())))
        threading.Thread(target=trabajo, daemon=True).start()

    def _listo(self, ind):
        self.indice = ind
        self._pie("✔ Actualizado. ")
        if self.e.get().strip():
            self.buscar()


# ======================================================================================= GUIA DE EMERGENCIA
class GuiaEmergencia(tk.Frame):
    """El proceso manual paso a paso (solo lectura; se puede seleccionar y copiar)."""

    def __init__(self, padre):
        super().__init__(padre, bg=P.C["bg"])
        b = ad.Flujo(self, P.C["bg"], hueco=6)
        b.pack(fill="x", pady=(0, 8))
        tk.Label(b, text="Si el automatismo no funciona, siga estos pasos a mano. Los comandos van en verde.",
                 bg=P.C["bg"], fg=P.C["mut"], font=(FONT, 9)).pack(side="left")
        P.BOTON(b, "Guardar como texto…", self._guardar, False, 20).pack(side="left", padx=(12, 0))
        marco = tk.Frame(self, bg=P.C["card2"])
        marco.pack(fill="both", expand=True)
        sb = tk.Scrollbar(marco)
        sb.pack(side="right", fill="y")
        t = tk.Text(marco, height=32, bg=P.C["card2"], fg=P.C["txt"], insertbackground=P.C["txt"], relief="flat",
                    wrap="word", font=(FONT, 10), padx=14, pady=10, yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.config(command=t.yview)
        t.tag_configure("titulo", font=(FONT, 12, "bold"), foreground=P.C["acc"], spacing1=10, spacing3=4)
        t.tag_configure("cmd", font=MONO, foreground=P.C["ok"], lmargin1=18, lmargin2=18)
        t.tag_configure("txt", lmargin1=4, lmargin2=4, spacing3=2)
        for titulo, lineas in GUIA:
            t.insert("end", titulo + "\n", "titulo")
            for ln in lineas:
                if ln.startswith("$ "):
                    t.insert("end", ln[2:] + "\n", "cmd")
                else:
                    t.insert("end", ln + "\n", "txt")
        t.config(state="disabled")
        self.texto = t

    def _guardar(self):
        ruta = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Guardar la guía",
                                            defaultextension=".txt", initialfile="Guia_emergencia_IP_fija.txt",
                                            filetypes=[("Texto", "*.txt")])
        if not ruta:
            return
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto_guia())
        messagebox.showinfo("Guía", "Guardada en:\n%s" % ruta, parent=self.winfo_toplevel())


def texto_guia():
    out = ["GUIA DE EMERGENCIA - IP FIJA FTTx (proceso manual)", ""]
    for titulo, lineas in GUIA:
        out += [titulo.upper()] + [("    " + ln[2:]) if ln.startswith("$ ") else ln for ln in lineas] + [""]
    return "\n".join(out)


# ======================================================================================= PESTANA CONTINGENCIA
class PanelContingencia(tk.Frame):
    """Pestana 'Contingencia': Guia de emergencia y Buscador de IPs por nodo, en su propia seccion."""

    def __init__(self, padre, servicio, nodo_actual=lambda: ""):
        super().__init__(padre, bg=P.C["bg"])
        self.nodo_actual = nodo_actual
        tk.Label(self, text="Contingencia", bg=P.C["bg"], fg=P.C["txt"], font=(P.SERIF, 17, "bold")).pack(anchor="w")
        a = tk.Label(self, text="Para cuando el automatismo o el Hendrix no funcionan: el proceso manual paso a paso y "
                     "el buscador de IPs por nodo (del Excel del equipo).", bg=P.C["bg"], fg=P.C["mut"],
                     font=(FONT, 10), justify="left")
        a.pack(anchor="w", pady=(0, 8))
        ad.envolver(a)
        sel = ad.Flujo(self, P.C["bg"], hueco=6)
        sel.pack(fill="x", pady=(0, 10))
        self.b_guia = tk.Label(sel, text="⚠  Guía de emergencia", font=(FONT, 10, "bold"), padx=14, pady=6,
                               cursor="hand2")
        self.b_ips = tk.Label(sel, text="Buscador de IPs por nodo", font=(FONT, 10, "bold"), padx=14, pady=6,
                              cursor="hand2")
        self.b_guia.pack(side="left")
        self.b_ips.pack(side="left")
        self.b_guia.bind("<Button-1>", lambda e: self.ver("guia"))
        self.b_ips.bind("<Button-1>", lambda e: self.ver("ips"))
        self.guia = GuiaEmergencia(self)
        self.buscador = BuscadorIPs(self, servicio)
        self.vista = "guia"
        self.ver("guia")

    def ver(self, cual):
        self.vista = cual
        for f in (self.guia, self.buscador):
            f.pack_forget()
        (self.guia if cual == "guia" else self.buscador).pack(fill="both", expand=True)
        for b, k in ((self.b_guia, "guia"), (self.b_ips, "ips")):
            activo = k == cual
            b.config(bg=P.C["acc"] if activo else P.C["card2"], fg=P.C["on_acc"] if activo else P.C["acc"])
        if cual == "ips":
            self.buscador.refrescar(self.nodo_actual())
            self.buscador.e.focus_set()

    def refrescar(self):
        if self.vista == "ips":
            self.buscador.refrescar(self.nodo_actual())

    def detener_todo(self):
        pass
