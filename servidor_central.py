# -*- coding: utf-8 -*-
"""SERVIDOR CENTRAL DE REPARTO (fase 1).

Un solo PC (despues Azure) tiene la sesion de SharePoint y:
  * reparte las solicitudes libres entre los PEM CONECTADOS y DISPONIBLES (uno a la vez, por turno);
  * entrega a cada PEM sus casos cuando su aplicacion "late" (cada 15 s);
  * escribe en SharePoint el Est_Seg cuando el PEM documenta.
Los PEM no abren SharePoint.

PEM (el nombre debe ser EXACTAMENTE el de la columna PEM_ASIGNADO):
    python servidor_central.py --agregar "Nombre Apellido"     (muestra el token que se le entrega a esa persona)
    python servidor_central.py --token "Nombre Apellido"       (token nuevo: el anterior deja de servir)
    python servidor_central.py --quitar "Nombre Apellido"
    python servidor_central.py --lista
Correr:
    python servidor_central.py --simular --ver   (primera vez: inicia sesion y SOLO muestra a quien asignaria)
    python servidor_central.py                   (reparte de verdad)
Prueba sin SharePoint:
    python servidor_central.py --archivo items.json --simular

Datos del central: %LOCALAPPDATA%\\hac_zac\\central (aparte de los datos de la aplicacion del PEM, aunque sea el mismo PC).
"""
import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

PUERTO = 8765
CADA_S = 20
MAX_CUERPO = 64 * 1024


def carpeta_central():
    return os.environ.get("HAC_ZAC_CENTRAL") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "central")


def _preparar_datos():
    """El central usa su propia carpeta de datos (cola de Est_Seg, registro de SharePoint, log)."""
    d = carpeta_central()
    os.makedirs(d, exist_ok=True)
    os.environ["HAC_ZAC_DATOS"] = d
    return d


class Central:
    """Estado del reparto en memoria + archivo central.json. Seguro entre hilos (HTTP y ciclo de SharePoint)."""

    def __init__(self, carpeta, simular=False):
        from hac_zac import reparto
        self.R = reparto
        self.ruta = os.path.join(carpeta, "central.json")
        self.simular = simular
        self.correo_activo = False         # True si este central lee el correo (fase 2)
        self.whatsapp = None               # transporte con .enviar(tel, texto) (fase 3); None = no se envia
        self.clasificar = None             # IA: clasificar(texto, esperando_confirmacion) -> intencion
        self.wa_config = None              # whatsapp.json (verify_token, app_secret...) para el webhook
        self.wa_simulado = False           # sin WhatsApp real: el simulador puede escribir desde este PC
        import queue
        self.salida = queue.Queue()        # mensajes al tecnico; los envia un hilo aparte (no bloquea)
        self.lock = threading.RLock()
        try:
            with open(self.ruta, encoding="utf-8") as f:
                self.estado = json.load(f)
        except FileNotFoundError:
            self.estado = reparto.nuevo_estado()
        self.estado.setdefault("pems", {})
        self.estado.setdefault("asignaciones", {})

    def guardar(self):
        with self.lock:
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.estado, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.ruta)

    # ---------------------------------------------------------------- lo que pide la aplicacion del PEM
    def atender_latido(self, token, cuerpo, ahora=None):
        """-> (codigo_http, respuesta)."""
        from hac_zac import cola
        ahora = ahora or datetime.now()
        with self.lock:
            nombre = self.R.autenticar(self.estado, token)
            if not nombre:
                return 401, {"ok": False, "error": "Token no valido. Pidale uno nuevo al administrador."}
            documentadas = cuerpo.get("documentadas") or {}
            if not isinstance(documentadas, dict):
                return 400, {"ok": False, "error": "documentadas debe ser un objeto {id: estado}"}
            casos, pedir_sp = self.R.latido(self.estado, nombre, bool(cuerpo.get("disponible")), documentadas, ahora)
            ya = cola.estados_sp()
            confirmadas = []
            from hac_zac import agente
            for i, est in pedir_sp.items():
                self._encolar(agente.al_documentar(self.estado, i, est, ahora))   # una sola vez por caso
                if self.simular:
                    confirmadas.append(i)                     # en simulacion no se escribe en SharePoint
                elif i not in ya:
                    cola.pedir_estado_sp(i, est)              # lo escribe el ciclo de SharePoint
                elif ya[i].get("ok"):
                    confirmadas.append(i)
            self.guardar()
            return 200, {"ok": True, "pem": nombre, "casos": casos, "confirmadas": confirmadas,
                         "simulacion": self.simular, "correo_central": self.correo_activo, "hora": ahora.isoformat(timespec="seconds")}

    # ---------------------------------------------------------------- ciclo con SharePoint
    def repartir(self, items, asignar, log=print, ahora=None):
        """asignar(item, nombre) -> True si SharePoint acepto. Devuelve [(id, nombre)] asignadas."""
        ahora = ahora or datetime.now()
        hechas = []
        with self.lock:
            self.R.cerrar_por_sp(self.estado, items, ahora)
            plan = self.R.plan(self.estado, items, ahora)
        for it, nombre in plan:
            if self.simular:
                log("   [simulacion] solicitud %s -> %s" % (it.get("ID"), nombre))
                continue
            if asignar(it, nombre):
                from hac_zac import agente
                with self.lock:
                    self.R.registrar_asignacion(self.estado, it, nombre, ahora)
                    self._encolar(agente.al_asignar(self.estado, str(it.get("ID")), ahora), inicio_id=str(it.get("ID")))
                hechas.append((str(it.get("ID")), nombre))
                log("   solicitud %s asignada a %s" % (it.get("ID"), nombre))
        with self.lock:
            self.guardar()
        return hechas

    # ---------------------------------------------------------------- tecnico (WhatsApp, fase 3)
    def _encolar(self, mensajes, inicio_id=None):
        """inicio_id: es el PRIMER aviso de ese caso (WhatsApp exige plantilla aprobada para escribir primero)."""
        for tel, texto in mensajes or []:
            self.salida.put((tel, texto, inicio_id))

    def _enviar_uno(self, tel, texto, inicio_id):
        cfg = getattr(self.whatsapp, "c", None) or {}
        if inicio_id and cfg.get("plantilla_inicio"):
            params = (inicio_id,) if cfg.get("plantilla_con_id", True) else ()
            self.whatsapp.enviar_plantilla(tel, cfg["plantilla_inicio"], cfg.get("plantilla_idioma") or "es", params)
        else:
            self.whatsapp.enviar(tel, texto)

    def atender_mensaje_pem(self, token, cuerpo, ahora=None):
        """POST /mensaje: el PEM le escribe al tecnico desde su aplicacion (se reenvia literal)."""
        from hac_zac import agente
        ahora = ahora or datetime.now()
        with self.lock:
            nombre = self.R.autenticar(self.estado, token)
            if not nombre:
                return 401, {"ok": False, "error": "Token no valido."}
            try:
                msgs = agente.mensaje_pem(self.estado, str(cuerpo.get("id") or ""), nombre, cuerpo.get("texto"),
                                          "direccionamiento" if cuerpo.get("tipo") == "direccionamiento" else "mensaje",
                                          ahora)
            except ValueError as e:
                return 400, {"ok": False, "error": str(e)}
            self._encolar(msgs)
            self.guardar()
            return 200, {"ok": True, "whatsapp": self.whatsapp is not None}

    def atender_tecnico(self, tel, texto, ahora=None):
        """Mensaje entrante del tecnico (webhook de WhatsApp o simulador)."""
        from hac_zac import agente
        ahora = ahora or datetime.now()
        with self.lock:
            msgs = agente.mensaje_tecnico(self.estado, tel, texto, ahora, clasificar=self.clasificar)
            self._encolar(msgs)
            self.guardar()
        return msgs

    def enviar_pendientes(self, log=print, bloquear=False):
        """Envia la cola de salida por WhatsApp. Sin WhatsApp configurado solo se registra en el chat del caso."""
        import queue
        enviados = 0
        while True:
            try:
                tel, texto, inicio_id = self.salida.get(timeout=1 if bloquear else 0)
            except queue.Empty:
                return enviados
            if self.whatsapp is None:
                continue
            for intento in range(3):
                try:
                    self._enviar_uno(tel, texto, inicio_id)
                    enviados += 1
                    break
                except Exception as e:
                    log("   [whatsapp] no se pudo enviar a ...%s (intento %d): %s" % (tel[-4:], intento + 1, e))
                    time.sleep(2 * (intento + 1))

    def hilo_envios(self, parar):
        while not parar.is_set():
            try:
                self.enviar_pendientes(bloquear=True)
            except Exception:
                import logging
                logging.getLogger("hac_zac.central").exception("envios whatsapp")

    # ---------------------------------------------------------------- correo (un solo buzon para todos)
    def pendientes_correo(self):
        with self.lock:
            return self.R.pendientes_correo(self.estado)

    def guardar_correo(self, texto, hora, sol):
        """Lo llama el lector de correo cuando confirma el SOLICITUD ID. Devuelve el id o None."""
        with self.lock:
            ok = self.R.guardar_correo(self.estado, sol["id"], texto, hora)
            if ok:
                self.guardar()
        return sol["id"] if ok else None

    def tabla(self, ahora=None):
        with self.lock:
            filas = self.R.resumen(self.estado, ahora or datetime.now())
        out = []
        for f in filas:
            out.append("   %-28s %-12s %-14s %-10s %-9s %s" % (
                f["pem"][:28], "conectado" if f["conectado"] else "-", "DISPONIBLE" if f["disponible"] else "no disp.",
                f["abierta"] or "-", ("correo OK" if f["correo"] else "sin correo") if f["abierta"] else "",
                (f["ultimo"] or "")[11:16]))
        return out


def hilo_correo(central, ver=False, cada=60, debug=False, parar=None):
    """Lector de correo central: un solo Outlook (el buzon de la lista llega a todos). Cada `cada` segundos busca
    la cuenta RR de las asignaciones sin correo y guarda la plantilla cuando el SOLICITUD ID coincide."""
    import correo_lector
    import ms_login
    from hac_zac import credenciales
    from navegador import aplicar_visibilidad
    parar = parar or threading.Event()
    d = correo_lector.abrir(ver)
    cr = credenciales.cargar()
    en_outlook = lambda u: "outlook." in u.split("/")[2].lower() if "//" in u else False
    if not ms_login.asegurar_sesion(d, en_outlook, cr.get("ms_usuario", ""), cr.get("ms_clave", ""),
                                    mostrar=lambda: aplicar_visibilidad(d, "correo", True)):
        print("[correo] no se pudo iniciar sesion en Outlook en 5 minutos; se intentara en cada ciclo.")
    try:
        while not parar.is_set():
            try:
                pend = central.pendientes_correo()
                if pend:
                    aplicar_visibilidad(d, "correo")
                    try:
                        d.get(correo_lector.URL)
                        time.sleep(3)
                    except Exception:
                        pass
                    n = correo_lector.revisar(d, debug, pendientes=pend, guardar=central.guardar_correo)
                    print(time.strftime("%H:%M:%S"), "[correo] buscadas %d, plantillas nuevas %d" % (len(pend), n))
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "[correo] error:", e)
                import logging
                logging.getLogger("hac_zac.central").exception("correo")
            parar.wait(cada)
    finally:
        d.quit()


def crear_servidor(central, puerto=PUERTO, host="0.0.0.0"):
    class Manejador(BaseHTTPRequestHandler):
        server_version = "HacZacCentral/1"

        def log_message(self, fmt, *args):            # sin ruido en consola por cada latido
            pass

        def _responder(self, codigo, datos):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            from urllib.parse import parse_qsl, urlsplit
            u = urlsplit(self.path)
            if u.path == "/salud":
                return self._responder(200, {"ok": True, "servicio": "hac_zac_central", "simulacion": central.simular})
            if u.path == "/whatsapp":                   # Meta verifica el webhook al registrarlo
                from hac_zac import whatsapp
                ch = whatsapp.verificar_suscripcion(dict(parse_qsl(u.query)),
                                                    (central.wa_config or {}).get("verify_token"))
                if ch is None:
                    return self._responder(403, {"ok": False})
                cuerpo = ch.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
                return
            return self._responder(404, {"ok": False, "error": "no existe"})

        def _whatsapp(self, crudo):
            """Mensajes del tecnico. Con WhatsApp real, solo si la firma de Meta es valida; en modo simulado,
            solo desde este mismo PC."""
            from hac_zac import whatsapp
            cfg = central.wa_config or {}
            if cfg.get("app_secret"):
                if not whatsapp.firma_valida(crudo, self.headers.get("X-Hub-Signature-256"), cfg["app_secret"]):
                    return self._responder(403, {"ok": False, "error": "firma invalida"})
            elif not (central.wa_simulado and self.client_address[0] in ("127.0.0.1", "::1")):
                return self._responder(403, {"ok": False, "error": "webhook sin configurar"})
            try:
                payload = json.loads(crudo.decode("utf-8") or "{}")
            except ValueError:
                return self._responder(400, {"ok": False})
            mensajes = whatsapp.extraer_mensajes(payload)
            self._responder(200, {"ok": True})        # Meta pide responder rapido; se atiende despues

            def atender():
                for tel, texto, _ in mensajes:
                    try:
                        central.atender_tecnico(tel, texto)
                    except Exception:
                        import logging
                        logging.getLogger("hac_zac.central").exception("mensaje del tecnico")
            threading.Thread(target=atender, daemon=True).start()

        def do_POST(self):
            if self.path not in ("/latido", "/mensaje", "/whatsapp"):
                return self._responder(404, {"ok": False, "error": "no existe"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_CUERPO:
                return self._responder(413, {"ok": False, "error": "cuerpo muy grande"})
            crudo = self.rfile.read(n)
            if self.path == "/whatsapp":
                return self._whatsapp(crudo)
            try:
                cuerpo = json.loads(crudo.decode("utf-8") or "{}")
                if not isinstance(cuerpo, dict):
                    raise ValueError
            except ValueError:
                return self._responder(400, {"ok": False, "error": "JSON invalido"})
            auth = self.headers.get("Authorization") or ""
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            try:
                if self.path == "/mensaje":
                    codigo, datos = central.atender_mensaje_pem(token, cuerpo)
                else:
                    codigo, datos = central.atender_latido(token, cuerpo)
            except Exception as e:                      # nunca tumbar el servidor por un pedido
                import logging
                logging.getLogger("hac_zac.central").exception("latido")
                codigo, datos = 500, {"ok": False, "error": "error interno: %s" % e}
            return self._responder(codigo, datos)

    srv = ThreadingHTTPServer((host, puerto), Manejador)
    srv.daemon_threads = True
    return srv


def _gestionar_pems(a, central):
    R = central.R
    with central.lock:
        if a.agregar:
            t = R.agregar_pem(central.estado, a.agregar)
            print("PEM agregado: %s\nToken (entreguelo SOLO a esa persona; va en Ajustes > Reparto central):\n  %s"
                  % (a.agregar.strip(), t))
        if a.token:
            if a.token not in central.estado["pems"]:
                sys.exit("No existe el PEM %r (use --lista)" % a.token)
            print("Token nuevo de %s:\n  %s" % (a.token, R.nuevo_token(central.estado, a.token)))
        if a.quitar:
            R.quitar_pem(central.estado, a.quitar)
            print("Quitado:", a.quitar)
        central.guardar()
    print("\n".join(central.tabla()) or "   (sin PEM: use --agregar)")


def _preparar_agente(central, carpeta, simulado=False):
    """WhatsApp (real, simulado o ninguno) e IA (opcional: sin ella el agente usa reglas)."""
    from hac_zac import ia, whatsapp
    cfg = whatsapp.cargar_config(carpeta)
    if simulado:
        central.whatsapp, central.wa_simulado = whatsapp.Consola(carpeta), True
        print("WhatsApp: SIMULADO (los mensajes se anotan en whatsapp_salida.jsonl; use chat_tecnico.py).")
    elif cfg:
        central.whatsapp, central.wa_config = whatsapp.Cliente(cfg), cfg
        print("WhatsApp: activo (numero %s). Webhook: <su URL https>/whatsapp" % cfg["phone_number_id"])
        if not cfg.get("app_secret"):
            print("   AVISO: sin app_secret no se aceptan mensajes del tecnico (configure con --configurar-whatsapp).")
    else:
        print("WhatsApp: sin configurar (el agente no envia nada). Use --configurar-whatsapp o --whatsapp-simulado.")
    icfg = ia.cargar_config(carpeta)
    if icfg:
        central.clasificar = ia.Clasificador(icfg)
        print("IA: %s (%s) para entender los mensajes del tecnico." % (icfg["deployment"], icfg["endpoint"]))
    else:
        print("IA: sin configurar; el agente entiende por palabras clave (--configurar-ia para usar gpt-5-mini).")


def _configurar(a, carpeta):
    import getpass
    from hac_zac import ia, whatsapp

    def pedir(texto, actual="", secreto=False):
        sug = " [Enter = dejar el actual]" if actual else ""
        v = (getpass.getpass if secreto else input)("%s%s: " % (texto, sug)).strip()
        return v or actual

    if a.configurar_whatsapp:
        c = whatsapp.cargar_config(carpeta) or {}
        print("Datos de Meta for Developers > su app > WhatsApp > Configuracion de la API.")
        c["phone_number_id"] = pedir("Identificador del numero de telefono (phone_number_id)", c.get("phone_number_id", ""))
        c["token"] = pedir("Token de acceso (no se muestra)", c.get("token", ""), True)
        c["verify_token"] = pedir("Verify token (invente una palabra; la misma va en Meta > Webhook)",
                                  c.get("verify_token", ""))
        c["app_secret"] = pedir("Clave secreta de la app (Configuracion > Basica; no se muestra)",
                                c.get("app_secret", ""), True)
        c["plantilla_inicio"] = pedir("Plantilla para el primer aviso (ej. hello_world; vacio = texto)",
                                      c.get("plantilla_inicio", ""))
        c["plantilla_idioma"] = pedir("Idioma de la plantilla (es, es_CO, en_US)", c.get("plantilla_idioma", "es"))
        c["plantilla_con_id"] = pedir("¿La plantilla tiene la variable {{1}} = solicitud? (si/no)",
                                      "si" if c.get("plantilla_con_id", True) else "no").lower().startswith("s")
        whatsapp.guardar_config(carpeta, c)
        print("Guardado (token y clave cifrados) en", os.path.join(carpeta, "whatsapp.json"))
    if a.configurar_ia:
        c = ia.cargar_config(carpeta) or {}
        c["endpoint"] = pedir("Endpoint de Azure OpenAI (https://<recurso>.openai.azure.com)", c.get("endpoint", ""))
        c["deployment"] = pedir("Nombre del despliegue", c.get("deployment", "gpt-5-mini"))
        c["api_key"] = pedir("API key (vacio = usar 'az login'; no se muestra)", c.get("api_key", ""), True)
        ia.guardar_config(carpeta, c)
        print("Guardado en", os.path.join(carpeta, "ia.json"))
    if a.probar_ia:
        c = ia.cargar_config(carpeta)
        if not c:
            sys.exit("IA sin configurar: use --configurar-ia")
        t0 = time.time()
        print("Intencion:", ia.Clasificador(c)(a.probar_ia), "(%.1f s)" % (time.time() - t0))


def main():
    ap = argparse.ArgumentParser(description="Servidor central de reparto HAC/ZAC")
    ap.add_argument("--agregar"), ap.add_argument("--quitar"), ap.add_argument("--token")
    ap.add_argument("--lista", action="store_true")
    ap.add_argument("--simular", action="store_true", help="no escribe en SharePoint: solo muestra a quien asignaria")
    ap.add_argument("--ver", action="store_true", help="mostrar el navegador (primera vez, para iniciar sesion)")
    ap.add_argument("--una", action="store_true")
    ap.add_argument("--cada", type=int, default=CADA_S)
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--archivo", help="items.json de prueba (sin SharePoint)")
    ap.add_argument("--sin-correo", action="store_true", help="no leer el correo aqui (cada PEM usa su lector)")
    ap.add_argument("--correo-cada", type=int, default=60, help="segundos entre revisiones del correo")
    ap.add_argument("--debug-correo", action="store_true", help="guarda outlook_debug_* para ajustar selectores")
    ap.add_argument("--demo", action="store_true",
                    help="con --archivo: asigna de verdad EN MEMORIA (sin SharePoint) para probar el agente")
    ap.add_argument("--whatsapp-simulado", action="store_true",
                    help="no envia por WhatsApp: anota los mensajes y acepta el simulador (chat_tecnico.py)")
    ap.add_argument("--configurar-whatsapp", action="store_true")
    ap.add_argument("--configurar-ia", action="store_true")
    ap.add_argument("--probar-ia", metavar="TEXTO", help="clasifica un mensaje de prueba con la IA y sale")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)     # que cada linea se vea al momento (consola o ventana)
    except Exception:
        pass

    carpeta = _preparar_datos()
    if a.configurar_whatsapp or a.configurar_ia or a.probar_ia:
        return _configurar(a, carpeta)
    central = Central(carpeta, simular=a.simular or (bool(a.archivo) and not a.demo))
    if a.agregar or a.quitar or a.token or a.lista:
        _gestionar_pems(a, central)
        return
    if not central.estado["pems"]:
        sys.exit('No hay PEM registrados. Agregue cada uno con:  python servidor_central.py --agregar "Nombre Apellido"')

    _preparar_agente(central, carpeta, a.whatsapp_simulado)
    parar_envios = threading.Event()
    threading.Thread(target=central.hilo_envios, args=(parar_envios,), daemon=True, name="envios").start()
    srv = crear_servidor(central, a.puerto)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Servidor central escuchando en el puerto %d%s. Datos: %s"
          % (a.puerto, "  [SIMULACION: no escribe en SharePoint]" if central.simular else "", carpeta), flush=True)

    if a.archivo:
        with open(a.archivo, encoding="utf-8") as f:
            items = json.load(f)
        asignar = (lambda it, n: True) if a.demo else (lambda it, n: False)
        central.repartir(items, asignar)
        print("\n".join(central.tabla()))
        if a.una:
            return
        print("Escuchando latidos (Ctrl+C para salir)...")
        try:
            while True:
                time.sleep(a.cada)
                central.repartir(items, asignar)
        except KeyboardInterrupt:
            return

    import ms_login
    import sp_lector
    from hac_zac import credenciales
    from navegador import aplicar_visibilidad
    d = sp_lector.abrir(a.ver)
    cr = credenciales.cargar()
    if not ms_login.asegurar_sesion(d, sp_lector.url_es_sharepoint, cr.get("ms_usuario", ""), cr.get("ms_clave", ""),
                                    mostrar=lambda: aplicar_visibilidad(d, "sp", True)):
        print("No se pudo iniciar sesion en SharePoint en 5 minutos; se intentara en cada ciclo.")
    parar_correo = threading.Event()
    if not a.sin_correo:
        # 6 s despues: dos Chrome arrancando a la vez se pisan al preparar el driver
        threading.Timer(6, lambda: threading.Thread(
            target=hilo_correo, args=(central, a.ver, a.correo_cada, a.debug_correo, parar_correo),
            daemon=True, name="correo-central").start()).start()
        central.correo_activo = True
        print("Lector de correo central: activo (cada %d s)." % a.correo_cada)
    try:
        while True:
            try:
                if not central.simular and sp_lector.enviar_estados_pendientes(d):
                    time.sleep(1)
                items = sp_lector.leer_items(d)
                central.repartir(items, lambda it, n: bool(sp_lector.asignar_item(d, it, n)))
                print(time.strftime("%H:%M:%S"), "leidas %d solicitudes" % len(items), flush=True)
                print("\n".join(central.tabla()), flush=True)
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "error:", e, flush=True)
                import logging
                logging.getLogger("hac_zac.central").exception("ciclo")
            if a.una:
                break
            try:
                d.refresh()
            except Exception:
                pass
            time.sleep(a.cada)
    finally:
        parar_correo.set()
        parar_envios.set()
        srv.shutdown()
        d.quit()


if __name__ == "__main__":
    main()
