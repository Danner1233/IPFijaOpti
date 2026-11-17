# -*- coding: utf-8 -*-
"""Servicio de historial, plantilla y documentacion (sin interfaz: se puede probar solo).

* Cada solicitud se guarda como <carpeta de datos>/solicitudes/<ID o RR><n>.json con todo para reabrirla:
  datos pegados, resultado de la operacion, segmentos/IP libres, IP elegidas, plantilla (con ediciones),
  ruta del .txt, intentos y fecha de documentacion. Nunca guarda contrasenas.
* La memoria de IPs de Capa 2 es historial_capa2.json (la misma que usa el script de SecureCRT).
"""
import json
from datetime import datetime
from pathlib import Path

from . import documentacion as doc
from . import estados, registro
from . import plantilla as pl
from .historial_capa2 import HistorialCapa2
from .rutas import data_dir
from .segmentos import segmento_de_ip
from .solicitudes import SolicitudStore

AJUSTES_DEFECTO = {"configurador": "DANNER ARIAS", "carpeta_plantillas": "", "formato_carpeta": "%m-%d", "pem_nombre": "", "auto_asignar": True, "securecrt_exe": "", "sesion_crt": "", "servidor_central": "", "carpeta_equipo": "", "subcarpeta_dia": True, "modo_avanzado": False,
                    "auto_procesar": False, "flujo_al_abrir": False, "ver_sp": True, "ver_correo": True, "ver_portal": True}


def cargar_ajustes() -> dict:
    ruta = data_dir() / "ajustes.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        datos = {}
    return {**AJUSTES_DEFECTO, **{k: v for k, v in datos.items() if k in AJUSTES_DEFECTO}}


def guardar_ajustes(ajustes: dict) -> None:
    (data_dir() / "ajustes.json").write_text(json.dumps(ajustes, ensure_ascii=False, indent=2), encoding="utf-8")


def estado_texto(rec: dict) -> str:
    if rec.get("documentada_en"):
        return "Documentada"
    if rec.get("archivo"):
        return "Guardada"
    if (rec.get("preview") or "").strip():
        return "Plantilla generada"
    if rec.get("operacion"):
        return "Operación hecha"
    return "Datos pegados"


class Servicio:
    def __init__(self):
        self.store = SolicitudStore()
        self.ips = HistorialCapa2()
        self.ajustes = cargar_ajustes()

    # ------------------------------------------------------------------ plantilla
    def datos_plantilla(self, rec: dict) -> pl.DatosPlantilla:
        op = rec.get("operacion") or {}
        segs = op.get("segmentos") or []
        ip, ipb = (rec.get("ip") or "").strip(), (rec.get("ip_bridge") or "").strip()

        def mg(x):
            s = segmento_de_ip(segs, x)
            return (s["mascara"], s["gateway"], s["prefijo"]) if s else ("", "", None)

        m, g, p = mg(ip)
        mb, gb, _ = mg(ipb)
        return pl.DatosPlantilla(
            configurador=self.ajustes.get("configurador", ""), solicitud=rec.get("txt_sol", ""),
            acs=rec.get("txt_acs", ""), solicitud_id=rec.get("id", ""), dis_cur_int=op.get("bloque_interfaz", ""),
            capa2=op.get("capa2_nombre", ""), capa2_ip=op.get("capa2_ip", ""), rr=rec.get("rr", ""),
            ip=ip, mascara=m, gateway=g, ip_bridge=ipb, mascara_bridge=mb, gateway_bridge=gb, prefijo=p,
            validacion_l2=op.get("validacion_red", ""),
            switch_previa=op.get("previa_switch", ""), switch_config=op.get("config_switch", ""),
            velocidad_previa=op.get("previa_velocidad", ""), velocidad_config=op.get("config_velocidad", ""),
            bridge_previa=op.get("previa_bridge", ""), bridge_config=op.get("config_bridge", ""),
            ping=rec.get("txt_ping", ""))

    def generar(self, rec: dict) -> str:
        return pl.construir_plantilla(self.datos_plantilla(rec))

    # ------------------------------------------------------------------ registro de operaciones
    def registrar_operacion(self, fase: str, res: dict, mensaje: str, inicio: str):
        """Guarda/actualiza la solicitud con el resultado del script. Devuelve el registro (o None)."""
        txt_sol = res.get("txt_sol", "") or ""
        sol = pl.parsear_solicitud(txt_sol) if txt_sol else {}
        sid = (res.get("solicitud_id") or sol.get("solicitud_id") or "").strip()
        rr = (res.get("rr") or sol.get("rr") or "").strip()
        key = SolicitudStore.clave(sid, rr)
        if not key:
            return None
        prev = self.store.cargar(key) or {}
        if not prev and sid and rr:                         # antes se guardo solo con la RR: se migra al ID
            antiguo = self.store.cargar(SolicitudStore.clave("", rr))
            if antiguo:
                prev = antiguo
                self.store.eliminar(SolicitudStore.clave("", rr))

        intentos = list(prev.get("intentos") or [])
        it = registro.intento(fase, res, mensaje, inicio)
        for i, x in enumerate(intentos):
            if x.get("inicio") == inicio:
                intentos[i] = it
                break
        else:
            intentos.append(it)

        op = registro.operacion(fase, res, mensaje, inicio)
        rec = dict(prev)
        rec.update({
            "key": key, "id": sid or prev.get("id", ""), "rr": rr, "cliente": res.get("cliente", ""),
            "red": op["tipo_red"], "capa2": op["capa2_nombre"],
            "txt_sol": txt_sol or prev.get("txt_sol", ""),
            "txt_acs": registro.texto_acs(res.get("portal")) or prev.get("txt_acs", ""),
            "txt_ping": prev.get("txt_ping", ""), "ip": prev.get("ip", ""), "ip_bridge": prev.get("ip_bridge", ""),
            "operacion": op, "intentos": intentos,
            "resultado": estados.resultado(intentos),   # una nueva operacion recalcula el estado
            "resultado_manual": "",
            "velocidad": res.get("velocidad", ""), "bridge": res.get("bridge", ""),
            "ip_ont": res.get("ip_ont", ""), "serial": res.get("serial", ""),
            "mac": res.get("mac", "") or prev.get("mac", ""),
            "ips_libres_finales": list(res.get("ips_libres_final") or []),
        })
        if not rec.get("editado"):
            rec["preview"] = self.generar(rec)
        rec["estado"] = estado_texto(rec)
        self.store.guardar(rec)
        return self.store.cargar(key)

    # ------------------------------------------------------------------ ediciones del usuario
    def actualizar(self, key: str, **campos):
        rec = self.store.cargar(key)
        if not rec:
            return None
        rec.update(campos)
        if ("ip" in campos or "ip_bridge" in campos or "txt_ping" in campos) and not rec.get("editado"):
            rec["preview"] = self.generar(rec)
        rec["estado"] = estado_texto(rec)
        self.store.guardar(rec)
        return self.store.cargar(key)

    def cambiar_resultado(self, key: str, estado: str):
        """Fija a mano Exitosa / Escalamiento / No exitosa."""
        if estado not in estados.OPCIONES_MANUALES:
            return None
        return self.actualizar(key, resultado=estado, resultado_manual=estado)

    def regenerar(self, key: str):
        rec = self.store.cargar(key)
        if not rec:
            return None
        rec["preview"] = self.generar(rec)
        rec["editado"] = False
        rec["estado"] = estado_texto(rec)
        self.store.guardar(rec)
        return self.store.cargar(key)

    def guardar_texto(self, key: str, texto: str, editado: bool):
        return self.actualizar(key, preview=texto, editado=editado)

    # ------------------------------------------------------------------ archivo .txt
    def guardar_txt(self, key: str, texto: str, nombre: str = ""):
        rec = self.store.cargar(key)
        if not rec:
            raise ValueError("Solicitud no encontrada")
        base = self.ajustes.get("carpeta_plantillas", "")
        fmt = self.ajustes.get("formato_carpeta", "%m-%d") if self.ajustes.get("subcarpeta_dia", True) else "-"
        actual = rec.get("archivo")
        if nombre:
            ruta = pl.ruta_con_nombre(base, fmt, nombre)
        elif actual and Path(actual).exists():
            ruta = Path(actual)
        else:
            ruta = pl.ruta_destino(base, fmt, rec.get("rr", ""), rec.get("cliente", ""))
        pl.guardar(texto, ruta)
        rec.update(preview=texto, archivo=str(ruta))
        rec["estado"] = estado_texto(rec)
        self.store.guardar(rec)
        return ruta

    # ------------------------------------------------------------------ documentacion (Microsoft Forms)
    def revisar_documentacion(self, texto: str):
        d = doc.parse(texto)
        return d, doc.missing_fields(d), doc.documentada_hoy(d)

    def documentar(self, key: str, texto: str, confirmar, log=lambda t: None, tras_envio=None) -> str:
        """Diligencia Forms con la plantilla. Devuelve 'enviado' o 'cancelado' (FormsError si falla)."""
        from .forms_bot import ejecutar_formulario
        d = doc.parse(texto)
        r = ejecutar_formulario(d, confirmar, log, tras_envio)
        if r == "enviado":
            rec = self.store.cargar(key) or {}
            if rec:
                rec["documentada_en"] = datetime.now().isoformat(timespec="seconds")
                rec["estado"] = estado_texto(rec)
                self.store.guardar(rec)
                self._pedir_estado_sp(rec)
        return r

    @staticmethod
    def estado_sp_de(rec: dict):
        """(id, estado) que quedara en SharePoint al documentar esta solicitud; None si no tiene ID o no hay un
        estado (ya no se escribe 'No exitosa' por defecto: asi se daño la 64849)."""
        from . import estados
        id_ = str((rec or {}).get("id") or "").strip()
        est = estados.normalizar((rec or {}).get("resultado") or "")
        if not id_ or not est:
            return None
        return id_, est

    @staticmethod
    def _pedir_estado_sp(rec: dict) -> None:
        """Documentada: la solicitud queda Exitosa / No exitosa / Escalamiento en SharePoint, con su causa y la
        observacion del PEM (lo escribe el lector de SharePoint) y se libera para que pueda tomar otra."""
        from . import cola
        try:
            par = Servicio.estado_sp_de(rec)
            if par:
                cola.pedir_estado_sp(par[0], par[1], rec.get("causa", ""), rec.get("observacion", ""),
                                     cola.nombre_configurado())
                cola.cambiar_estado(par[0], "terminada")
        except Exception:
            from . import log
            log.obtener("servicio").exception("no se pudo pedir el estado final a SharePoint")

    def aplicar_resultado(self, key: str, estado: str, causa: str = "", observacion: str = ""):
        """Estado + causa + observacion elegidos por el PEM. Si la solicitud ya estaba documentada, se actualiza
        tambien en SharePoint."""
        from . import causas
        if estado not in estados.OPCIONES_MANUALES:
            return None
        if not causas.requiere_causa(estado):
            causa = ""
        rec = self.actualizar(key, resultado=estado, resultado_manual=estado, causa=causa,
                              observacion=(observacion or "").strip())
        if rec and rec.get("documentada_en"):
            self._pedir_estado_sp(rec)
        return rec

    # ------------------------------------------------------------------ consulta
    def listar(self, filtro: str = ""):
        regs = self.store.listar()
        f = (filtro or "").strip().lower()
        if not f:
            return regs
        return [r for r in regs if f in " ".join(str(r.get(k, "")) for k in
                                                 ("id", "rr", "cliente", "red", "capa2", "resultado", "estado")).lower()]
