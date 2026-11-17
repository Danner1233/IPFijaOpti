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
            for i, est in pedir_sp.items():
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
                with self.lock:
                    self.R.registrar_asignacion(self.estado, it, nombre, ahora)
                hechas.append((str(it.get("ID")), nombre))
                log("   solicitud %s asignada a %s" % (it.get("ID"), nombre))
        with self.lock:
            self.guardar()
        return hechas

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
            if self.path == "/salud":
                return self._responder(200, {"ok": True, "servicio": "hac_zac_central", "simulacion": central.simular})
            return self._responder(404, {"ok": False, "error": "no existe"})

        def do_POST(self):
            if self.path != "/latido":
                return self._responder(404, {"ok": False, "error": "no existe"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_CUERPO:
                return self._responder(413, {"ok": False, "error": "cuerpo muy grande"})
            try:
                cuerpo = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if not isinstance(cuerpo, dict):
                    raise ValueError
            except ValueError:
                return self._responder(400, {"ok": False, "error": "JSON invalido"})
            auth = self.headers.get("Authorization") or ""
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            try:
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
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)     # que cada linea se vea al momento (consola o ventana)
    except Exception:
        pass

    carpeta = _preparar_datos()
    central = Central(carpeta, simular=a.simular or bool(a.archivo))
    if a.agregar or a.quitar or a.token or a.lista:
        _gestionar_pems(a, central)
        return
    if not central.estado["pems"]:
        sys.exit('No hay PEM registrados. Agregue cada uno con:  python servidor_central.py --agregar "Nombre Apellido"')

    srv = crear_servidor(central, a.puerto)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Servidor central escuchando en el puerto %d%s. Datos: %s"
          % (a.puerto, "  [SIMULACION: no escribe en SharePoint]" if central.simular else "", carpeta), flush=True)

    if a.archivo:
        with open(a.archivo, encoding="utf-8") as f:
            items = json.load(f)
        central.repartir(items, lambda it, n: False)
        print("\n".join(central.tabla()))
        if a.una:
            return
        print("Escuchando latidos (Ctrl+C para salir)...")
        try:
            while True:
                time.sleep(a.cada)
                central.repartir(items, lambda it, n: False)
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
        srv.shutdown()
        d.quit()


if __name__ == "__main__":
    main()
