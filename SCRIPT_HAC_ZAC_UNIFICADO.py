# $language = "python"
# $interface = "1.0"

"""
buscar_ips_libres_crt.py  (version unificada HAC + ZAC)

Automatiza:
1. Abre la interfaz (hac_zac_gui.py) y recibe SERIAL o MAC, MEGAS y BRIDGE.
   IP ONT, SN, cliente y RR se sacan SOLOS del Support Portal (portal_csr.py).
   Todo el proceso corre de corrido, sin alertas: el avance, los errores y la
   plantilla de resultados se muestran en la interfaz.
2. Ingresa siempre a A9KTRIARA2.
3. Ejecuta BGP para descubrir el Capa 3 real.
4. Sale de A9KTRIARA2 e ingresa al Capa 3 descubierto.
5. Obtiene interfaz, Capa 2 (HAC/ZAC), IPs libres (Incomplete).
6. La IP del Capa 2 se consulta AUTOMATICAMENTE en la base
   historial_capa2.json (ya NO se usa kou). Si el Capa 2 no esta
   en la base, se pide la IP una vez y, tras un login exitoso, se
   guarda para las proximas veces.
7. Todos los SSH responden "yes" SOLO si aparece la pregunta de huella
   (yes/no), nunca a ciegas, y detectan clave rechazada / timeout.
8. HAC: velocidad (traffic-table), descripcion, bridge ETH4.
   ZAC: service-port 5, bridge, name + description.
9. Al final vuelve al Capa 3 y muestra de nuevo las IPs libres.
"""

import io
import json
import os
import re
import subprocess
import tempfile
import time


VRF = "PROVISION_NACIONAL_HPE"
# Credenciales: NUNCA aqui. Se escriben en la interfaz (Ajustes) y se guardan cifradas en credenciales.json.
USUARIO = ""
CLAVE = ""

# Base de Capa 2 (nombre -> IP). Si se deja vacio, se busca
# "historial_capa2.json" en la MISMA carpeta de este script.
# Tambien puede ponerse una ruta fija, ej: r"C:\\Users\\dann\\historial_capa2.json"
HISTORIAL_CAPA2 = ""

# ---------------- Consulta al Support Portal (Selenium) ----------------
# SecureCRT no ejecuta Selenium directamente: este script llama a
# portal_csr.py (misma carpeta) con el Python del sistema.
PORTAL_USUARIO = ""
PORTAL_CLAVE = ""
PYTHON_EXE = "python"      # o "py", o la ruta completa a python.exe
PORTAL_SCRIPT = ""         # vacio = portal_csr.py junto a este script
GUI_SCRIPT = ""            # vacio = hac_zac_gui.py junto a este script


# Velocidades soportadas en HAC (CIR del DOWN en kbps).
CIR_POR_VELOCIDAD = {
    "30": 32960,
    "45": 49472,
    "50": 54976,
    "75": 82496,
    "80": 88000,
    "250": 281600,
    "300": 329984,
    "350": 394240,
    "450": 506880,
    "500": 549760,
    "550": 619520,
    "650": 732160,
    "950": 1024000,
    "1000": 1024000,
    "1024": 1024000,
    "9000": 9000000,
}

# Perfil exacto del DOWN. 950/1000/1024 comparten CIR, por eso se usan
# tambien CBS/PIR/PBS para dar prioridad al perfil correcto.
PERFIL_DOWN = {
    "30": (32960, 660000, 32960, 660000),
    "45": (49472, 989440, 49472, 989440),
    "50": (54976, 1099520, 54976, 1099520),
    "75": (82496, 1649920, 82496, 1649920),
    "80": (88000, 1760000, 88000, 1760000),
    "250": (281600, 4399360, 281600, 4399360),
    "300": (329984, 6599680, 329984, 6599680),
    "350": (394240, 6599680, 394240, 6599680),
    "450": (506880, 6599680, 506880, 6599680),
    "500": (549760, 10995200, 549760, 10995200),
    "550": (619520, 6599680, 619520, 6599680),
    "650": (732160, 10995200, 732160, 10995200),
    "950": (1024000, 6599680, 1024000, 6599680),
    "1000": (1024000, 6599680, 1024000, 6599680),
    "1024": (1024000, 6599680, 1024000, 6599680),
}


class LoginError(Exception):
    """
    Se lanza cuando un login SSH falla o se queda sin respuesta.
    de_red=True indica que el equipo no respondio (IP mala, sin ruta,
    timeout) y NO que la clave fue rechazada.
    """
    def __init__(self, mensaje, de_red=False):
        Exception.__init__(self, mensaje)
        self.de_red = de_red


class ProcesoError(Exception):
    """Error que detiene el proceso y se muestra en la interfaz (sin alertas)."""
    pass


class Cancelado(Exception):
    """El operador pulso Cancelar en la interfaz."""
    pass


def _json_atomico(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(datos, ensure_ascii=True))
    try:
        os.replace(tmp, ruta)
    except AttributeError:
        if os.path.exists(ruta):
            os.remove(ruta)
        os.rename(tmp, ruta)


def _leer_json(ruta):
    try:
        with open(ruta, "r") as f:
            return json.loads(f.read())
    except Exception:
        return None


class Ui(object):
    """Puente con hac_zac_gui.py mediante archivos JSON en una carpeta temporal."""

    PASOS = [
        "Consultando el Support Portal",
        "Entrando al A9K y descubriendo el Capa 3",
        "Leyendo ruta, interfaz y Capa 2",
        "Buscando IPs libres",
        "Entrando al Capa 2",
        "Configurando velocidad y descripcion",
        "Verificando y cerrando",
    ]

    def __init__(self, carpeta):
        self.dir = carpeta
        self.proc = None
        self.seq = 0
        self.fase = "esperando"
        self.paso_actual = 0
        self.mensaje = ""
        self.pregunta = None
        self.resultado = None
        self.error = None
        self.lineas = []
        self.n_pregunta = 0
        # Ultimo final (fin / error / cancelado) que se sigue enviando mientras espera: si la interfaz estaba
        # ocupada y no alcanzo a leerlo (dura ~2 s antes de pasar a 'esperando'), lo recupera de aqui.
        self.ultimo = None

    def _ruta(self, nombre):
        return os.path.join(self.dir, nombre)

    def _escribir(self):
        self.seq += 1
        try:
            _json_atomico(self._ruta("estado.json"), {
                "seq": self.seq,
                "fase": self.fase,
                "paso": self.paso_actual,
                "pasos": self.PASOS,
                "mensaje": self.mensaje,
                "log": self.lineas[-150:],
                "pregunta": self.pregunta,
                "resultado": self.resultado,
                "error": self.error,
                "ultimo": self.ultimo,
            })
        except Exception:
            pass

    def gui_viva(self):
        return self.proc is None or self.proc.poll() is None

    def chequear(self):
        if os.path.exists(self._ruta("cancelar.flag")):
            raise Cancelado()

    def log(self, texto, nivel="info"):
        self.lineas.append({
            "t": time.strftime("%H:%M:%S"), "n": nivel, "m": str(texto)
        })
        self._escribir()

    def paso(self, n, mensaje=None):
        self.chequear()
        self.fase = "corriendo"
        self.paso_actual = n
        self.mensaje = mensaje or self.PASOS[n - 1]
        self.log(self.mensaje)

    def esperar_solicitud(self):
        """Espera a que el operador pulse Iniciar. None si cierra la ventana.
        Mientras espera, cada MANTENER_VIVA_S mantiene viva la sesion del jump host (ver mantener_sesion)."""
        self._escribir()
        ruta = self._ruta("solicitud.json")
        ultimo = time.time()
        while True:
            if time.time() - ultimo >= MANTENER_VIVA_S:
                mantener_sesion(self.log, abortar=lambda: os.path.exists(ruta))
                ultimo = time.time()
            if os.path.exists(ruta):
                datos = _leer_json(ruta)
                if datos:
                    try:
                        os.remove(ruta)      # consumida: la siguiente que aparezca es una solicitud nueva
                    except Exception:
                        pass
                    self.ultimo = None       # empieza otra: el final anterior ya no aplica
                    return datos
            if not self.gui_viva():
                return None
            crt.Sleep(300)

    def preguntar_ip(self, mensaje, equipo, tipo, error=None):
        """Pregunta en la interfaz la IP del Capa 2. None si cancela."""
        self.n_pregunta += 1
        self.fase = "pregunta"
        self.pregunta = {
            "id": self.n_pregunta,
            "mensaje": "{}\n\nEquipo: {} ({})\n\nIngrese la IP del Capa 2 "
                       "(se guardara en la base para la proxima vez).".format(
                           mensaje, equipo if equipo else "No identificado", tipo),
            "error": error,
        }
        ruta = self._ruta("respuesta.json")
        if os.path.exists(ruta):
            os.remove(ruta)
        self._escribir()

        while True:
            self.chequear()
            datos = _leer_json(ruta) if os.path.exists(ruta) else None
            if datos and datos.get("id") == self.n_pregunta:
                os.remove(ruta)
                self.pregunta = None
                self.fase = "corriendo"
                self._escribir()
                return (datos.get("ip") or "").strip() or None
            if not self.gui_viva():
                raise Cancelado()
            crt.Sleep(300)

    def nuevo_ciclo(self):
        """Deja la interfaz lista para OTRA solicitud (sin cerrar el script ni la ventana)."""
        crt.Sleep(1500)      # que la interfaz alcance a mostrar el resultado anterior
        if self.fase in ("fin", "error", "cancelado"):
            self.ultimo = {
                "seq": self.seq, "fase": self.fase, "paso": self.paso_actual, "pasos": self.PASOS,
                "mensaje": self.mensaje, "log": self.lineas[-150:], "pregunta": None,
                # copia: resultado es el mismo dict RES, que se vacia justo abajo
                "resultado": dict(self.resultado) if self.resultado else None, "error": self.error,
            }
        for nombre in ("cancelar.flag", "respuesta.json"):
            try:
                if os.path.exists(self._ruta(nombre)):
                    os.remove(self._ruta(nombre))
            except Exception:
                pass
        RES.clear()
        self.fase = "esperando"
        self.paso_actual = 0
        self.mensaje = ""
        self.pregunta = None
        self.resultado = None
        self.error = None
        self.lineas = []
        self._escribir()
        return self.gui_viva()

    def fin(self, resultado):
        self.fase = "fin"
        self.resultado = resultado
        self.paso_actual = len(self.PASOS)
        self.log("Proceso finalizado")

    def fallo(self, mensaje):
        self.resultado = RES
        self.fase = "error"
        self.error = str(mensaje)
        self.log(mensaje, "error")

    def cancelado(self):
        self.resultado = RES
        self.fase = "cancelado"
        self.log("Proceso cancelado", "warn")


UI = None   # se crea en main()
RES = {}    # datos para la plantilla de resultados


# Equipo Capa 3 inicial fijo
CAPA3_INICIAL = "A9KTRIARA2"


def ssh_login(destino, prompts_ok, timeout=30):
    """
    Hace SSH a 'destino' y maneja de forma robusta todo lo que puede
    aparecer antes del prompt final:

      - Pregunta de huella (yes/no) -> responde yes (pasa siempre que
        el usuario del jump host es nuevo y su known_hosts esta vacio).
      - Prompt de password -> envia CLAVE UNA sola vez. Si el password
        vuelve a pedirse, es que fue rechazado y se aborta.
      - Permission denied / Access denied / Authentication failed.
      - Connection refused / timed out / No route to host.
      - Timeout: si no aparece ningun prompt, aborta con un mensaje
        en vez de quedarse pegado para siempre.

    prompts_ok: lista de strings que indican login exitoso.
    Devuelve el indice (1-based) del prompt que coincidio.
    """
    errores = [
        "has been locked",
        "Permission denied",
        "Access denied",
        "Authentication failed",
        "Login incorrect",
        "Connection refused",
        "Connection timed out",
        "No route to host",
        "Could not resolve",
        "Host key verification failed",
    ]

    cargar_credenciales()
    if not USUARIO or not CLAVE:
        raise Exception("Faltan el usuario o la clave de los equipos. Escribalos en la interfaz: "
                        "Ajustes > SecureCRT (se guardan cifrados en su PC).")

    crt.Sleep(800)
    crt.Screen.Send("ssh {}@{}\r".format(USUARIO, destino))

    esperados = ["(yes/no", "assword:"] + errores + list(prompts_ok)
    n_fijos = 2 + len(errores)
    clave_enviada = False

    for _ in range(10):
        idx = crt.Screen.WaitForStrings(esperados, timeout)

        if idx == 0:
            # Cancelar el ssh colgado para dejar limpio el jump host
            crt.Screen.Send("\x03")
            crt.Sleep(800)
            raise LoginError(
                "Timeout esperando respuesta al hacer SSH a {}.\n\n"
                "Revise en la pantalla en que punto quedo "
                "(huella, password, banner, cambio de clave, etc.)."
                .format(destino),
                de_red=True
            )

        if idx == 1:  # pregunta de huella
            crt.Sleep(300)
            crt.Screen.Send("yes\r")
            continue

        if idx == 2:  # password
            if clave_enviada:
                crt.Screen.Send("\x03")
                crt.Sleep(800)
                raise LoginError(
                    "El password fue RECHAZADO al entrar a {}.\n\n"
                    "Usuario: {}\n"
                    "Verifique USUARIO/CLAVE al inicio del script."
                    .format(destino, USUARIO)
                )
            crt.Sleep(500)
            crt.Screen.Send(CLAVE + "\r")
            clave_enviada = True
            continue

        if idx <= n_fijos:  # alguno de los errores
            motivo = errores[idx - 3]

            if motivo == "has been locked":
                crt.Sleep(800)
                raise LoginError(
                    "La IP del jump host esta BLOQUEADA en {}.\n\n"
                    "El equipo rechazo la conexion por demasiados intentos "
                    "fallidos de login.\n\n"
                    "NO reintente: cada intento extiende el bloqueo.\n"
                    "Espere a que se libere o pida el desbloqueo, y "
                    "verifique que USUARIO/CLAVE sean correctos en ese "
                    "equipo.".format(destino)
                )

            raise LoginError(
                "Fallo el SSH a {}: {}".format(destino, motivo),
                de_red=motivo in (
                    "Connection refused",
                    "Connection timed out",
                    "No route to host",
                    "Could not resolve",
                )
            )

        # Prompt de exito.
        # IMPORTANTE: antes de enviar la clave se IGNORA. El prompt del
        # jump host termina en ">" y aparece en el eco del propio 'ssh',
        # lo que se confundia con el prompt ">" del HAC y mandaba
        # comandos ('enable') encima del "User password:".
        if not clave_enviada:
            continue

        return idx - n_fijos

    raise LoginError("No se pudo completar el login a {}.".format(destino))


def enviar_y_leer(comando, prompt):
    """Envia un comando y captura la salida hasta el siguiente prompt."""
    crt.Sleep(800)
    crt.Screen.Send(comando + "\r")
    return crt.Screen.ReadString(prompt)


def login_a9k():
    """Ingresa al A9KTRIARA2 desde el bastion/jump host."""
    # Prompt IOS XR: RP/0/RSP0/CPU0:A9KTRIARA2#
    ssh_login(CAPA3_INICIAL, ["#"])
    crt.Sleep(500)
    return "#"


def obtener_capa3_desde_bgp(salida_bgp):
    """
    Extrae la IP del Capa 3 desde una linea como:

    10.10.95.138 (metric 8520) from 10.10.94.1 (10.10.95.138)

    Devuelve:
        10.10.95.138
    """

    patron = re.compile(
        r"^\s*"
        r"(\d{1,3}(?:\.\d{1,3}){3})"
        r"\s+\(metric\s+\d+\)"
        r"\s+from\s+"
        r"\d{1,3}(?:\.\d{1,3}){3}"
        r"\s+\("
        r"\d{1,3}(?:\.\d{1,3}){3}"
        r"\)"
        r"\s*$",
        re.IGNORECASE
    )

    for linea in salida_bgp.splitlines():
        m = patron.search(linea)
        if m:
            return m.group(1)

    return None


def salir_a9k():
    """Sale del A9K inicial y vuelve al bastion/jump host."""
    crt.Sleep(500)
    crt.Screen.Send("exit\r")
    crt.Sleep(1500)


def login_capa3(ip_capa3):
    """Hace SSH al Capa 3 real descubierto mediante BGP."""
    # Prompt Huawei: <NOMBRE_EQUIPO>
    ssh_login(ip_capa3, ["<"])
    crt.Screen.ReadString(">", 10)
    crt.Sleep(1000)


def obtener_interfaz(salida_ruta):
    """Obtiene la interfaz de la primera fila de ruta IPv4."""

    for linea in salida_ruta.splitlines():
        partes = linea.split()

        if partes and re.match(
            r"^\d{1,3}(?:\.\d{1,3}){3}/\d+$",
            partes[0]
        ):
            return partes[-1]

    return None


def obtener_datos_ruta(salida_ruta):
    """Obtiene Destination/Mask y NextHop desde la tabla de ruteo."""
    for linea in salida_ruta.splitlines():
        partes = linea.split()
        if not partes or not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}/\d+$", partes[0]):
            continue

        destination_mask = partes[0]
        gateway = None

        for parte in partes[1:]:
            if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", parte):
                gateway = parte
                break

        return {
            "destination_mask": destination_mask,
            "gateway": gateway,
        }

    return None


def obtener_ip_y_mascara_interfaz(salida_config):
    """Obtiene la IP y mascara reales del comando 'ip address'."""
    patron = re.compile(
        r"\bip\s+address\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})\b",
        re.IGNORECASE
    )

    for linea in salida_config.splitlines():
        m = patron.search(linea)
        if m:
            return m.group(1), m.group(2)

    return None, None


def forzar_sufijo_201(interfaz):
    """Cambia solo los ultimos 3 digitos de la subinterfaz a 201."""

    m = re.match(r"^(.*\.)(\d+)$", interfaz)

    if not m:
        return interfaz

    prefijo, numero = m.groups()

    if len(numero) >= 3:
        return prefijo + numero[:-3] + "201"

    return interfaz


def obtener_capa2(salida_config):
    """Obtiene el Capa 2 desde description y clasifica ZAC / HAC / OH.

    OH = capa 2 de red ONNET/ATP (ej. OH_BOGALGDOH_I_7360_CentrodeGravedad2_8): se reconoce solo si empieza
    por OH_ / OH- / OH. (no por una palabra que tenga "OH" en medio). ZAC/HAC tienen prioridad.
    """

    patron = re.compile(
        r"\b((?:ZAC|HAC)[^\s()]+)",
        re.IGNORECASE
    )
    patron_oh = re.compile(
        r"(?<![A-Za-z0-9])(OH[_\-.][^\s()]+)",
        re.IGNORECASE
    )

    for linea in salida_config.splitlines():

        if "description" in linea.lower():

            m = patron.search(linea)

            if m:
                nombre = m.group(1)

                tipo = (
                    "ZAC"
                    if nombre.upper().startswith("ZAC")
                    else "HAC"
                )

                return tipo, nombre

            m = patron_oh.search(linea)

            if m:
                return "OH", m.group(1)

    return None, None


def copiar_al_portapapeles(texto):
    """Copia texto al portapapeles usando SecureCRT o Windows."""

    try:
        crt.Clipboard.Text = texto
        return
    except Exception:
        pass

    try:
        crt.Clipboard.SetText(texto)
        return
    except Exception:
        pass

    try:
        process = subprocess.Popen(
            "clip",
            stdin=subprocess.PIPE,
            shell=True
        )

        process.communicate(
            input=texto.encode("latin1")
        )

    except Exception:
        pass


def salir_capa3():
    """
    Sale de la sesion SSH del Capa 3 y vuelve al jump host.

    Envia UN quit y espera el aviso de cierre del jump host. Solo si no
    aparece ninguno (algunos Huawei piden un segundo quit) envia otro.
    """
    cierres = ["closed", "Disconnecting", "Connection to"]

    crt.Sleep(500)
    crt.Screen.Send("quit\r")

    if crt.Screen.WaitForStrings(cierres, 4) == 0:
        crt.Screen.Send("quit\r")
        crt.Screen.WaitForStrings(cierres, 4)

    crt.Sleep(800)


JUMP_PROMPT = [None]


def _linea_actual():
    """Texto de la linea donde esta el cursor (el prompt actual)."""
    try:
        fila = crt.Screen.CurrentRow
        return crt.Screen.Get(fila, 1, fila, crt.Screen.Columns).strip()
    except Exception:
        return ""


MANTENER_VIVA_S = 240      # cada 4 min, SOLO mientras se espera una solicitud


def mantener_sesion(log=None, abortar=None):
    """Que la sesion del jump host no se cierre nunca:
    * si esta conectada, envia un Enter en el prompt: el jump host no la cierra por inactividad;
    * si se cayo, la reconecta UNA vez (con la clave guardada) y espera, como mucho 45 s, a que quede lista.
    Solo se llama entre procesos (esperando solicitud). Si llega una solicitud (abortar() -> True) deja de esperar
    para atenderla. Devuelve 'ok', 'reconectada', 'interrumpida' o 'sin_conexion'. Nunca lanza error."""
    try:
        if crt.Session.Connected:
            # El Enter SOLO si el cursor esta en el prompt del jump host sin nada escrito: si alguien dejo un
            # comando a medias (o la pestana quedo en otro equipo), un Enter lo ejecutaria.
            base = (JUMP_PROMPT[0] or "").strip()
            if base and _linea_actual().strip() == base:
                crt.Screen.Send("\r")
                return "ok"
            return "ocupada"
    except Exception:
        return "sin_conexion"
    try:
        try:
            crt.Session.Connect()
        except Exception:
            crt.Session.Connect('/S "%s"' % crt.Session.Path)
    except Exception:
        pass
    if esperar_jump_host(45, abortar):
        if log:
            log("La sesion del jump host se habia cerrado: reconectada.", "warn")
        return "reconectada"
    if abortar and abortar():
        return "interrumpida"
    if log:
        log("ATENCION: la sesion del jump host esta desconectada. Reconectela en SecureCRT.", "warn")
    return "sin_conexion"


_PIDE_DATOS = ("assword", "login:", "username", "usuario:", "passcode", "(yes/no")


def esperar_jump_host(maximo_s=180, abortar=None):
    """Espera a que la sesion quede LISTA: conectada y en una linea que no pide usuario/clave. Se reconoce el prompt
    por su forma ($ # > ] al final) o porque la pantalla se queda quieta 2 s (cualquier prompt). Mientras tanto el
    usuario puede escribir la clave. Si abortar() devuelve True (llego una solicitud), deja de esperar.
    Devuelve True si quedo lista."""
    fin = time.time() + maximo_s
    ultima, quieta = None, 0
    while time.time() < fin:
        if abortar:
            try:
                if abortar():
                    return False
            except Exception:
                pass
        try:
            if crt.Session.Connected:
                linea = _linea_actual()
                baja = linea.lower()
                if linea and not any(p in baja for p in _PIDE_DATOS):
                    if linea[-1:] in ("$", "#", ">", "]", "%", ":"):
                        return True
                    quieta = quieta + 1 if linea == ultima else 0
                    if quieta >= 2:
                        return True
                ultima = linea
        except Exception:
            pass
        crt.Sleep(1000)
    return False


def recordar_jump_host():
    """Al arrancar la sesion esta en el jump host: se guarda su prompt para poder volver."""
    if JUMP_PROMPT[0] is None:
        linea = _linea_actual()
        if linea:
            JUMP_PROMPT[0] = linea


def volver_al_jump_host():
    """Sale de lo que haya quedado abierto (Capa 2 HAC/ZAC, Capa 3, A9K) hasta ver el prompt del jump host.
    Devuelve True si lo confirmo. Nunca lanza error y NO escribe en la interfaz (si lo hiciera, la interfaz
    volveria a registrar el resultado anterior)."""
    base = JUMP_PROMPT[0]
    if not base:
        return False
    try:
        for _i in range(8):
            crt.Screen.Send("\r")
            crt.Sleep(900)
            linea = _linea_actual()
            # mismo prompt (se compara el inicio: puede cambiar la ruta o la hora al final)
            if linea == base or (len(base) >= 4 and linea.startswith(base[:min(len(base), 10)])):
                return True
            alto = linea.upper()
            if "[Y/N]" in alto or "(Y/N)" in alto:
                cmd = "y"
            elif linea.endswith("#"):
                cmd = "exit"           # IOS XR (A9K) / ZAC
            elif linea.startswith("<") or linea.endswith(">"):
                cmd = "quit"           # Huawei (Capa 3) / HAC
            else:
                cmd = "exit"
            crt.Screen.Send(cmd + "\r")
            crt.Sleep(1500)
    except Exception:
        pass
    return False


def ruta_historial():
    """Ruta del JSON con la base de Capa 2."""
    if HISTORIAL_CAPA2:
        return HISTORIAL_CAPA2

    try:
        base = os.path.dirname(crt.ScriptFullName)
    except Exception:
        base = os.path.expanduser("~")

    return os.path.join(base, "historial_capa2.json")


def normalizar_nombre(nombre):
    """Llave de busqueda: mayusculas, sin espacios ni puntuacion final."""
    return str(nombre or "").strip().rstrip(".,;:").upper()


def ip_valida(ip):
    if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", str(ip or "")):
        return False
    return all(int(o) <= 255 for o in ip.split("."))


def cargar_historial():
    """
    Carga la base de Capa 2. Devuelve (datos, puede_guardar).

    Si el archivo existe pero no se puede leer, puede_guardar=False
    para NUNCA sobreescribir una base que no se pudo interpretar.
    """
    ruta = ruta_historial()

    if not os.path.exists(ruta):
        return {}, True

    try:
        with io.open(ruta, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)

        if not isinstance(datos, dict):
            raise ValueError("el JSON no es un diccionario")

        return datos, True

    except Exception as e:
        UI.log(
            "No se pudo leer la base de Capa 2 ({}): {}. Se pedira la IP "
            "manual y NO se guardaran cambios en la base.".format(ruta, e),
            "warn"
        )
        return {}, False


def guardar_historial(datos):
    """Guarda la base de forma segura (temporal + backup + reemplazo)."""
    ruta = ruta_historial()
    tmp = ruta + ".tmp"

    try:
        contenido = json.dumps(
            datos, indent=1, sort_keys=True, ensure_ascii=True
        )

        with open(tmp, "w") as f:
            f.write(contenido)

        if os.path.exists(ruta):
            try:
                import shutil
                shutil.copyfile(ruta, ruta + ".bak")
            except Exception:
                pass

        try:
            os.replace(tmp, ruta)
        except AttributeError:
            # Python 2: rename no sobreescribe en Windows
            if os.path.exists(ruta):
                os.remove(ruta)
            os.rename(tmp, ruta)

        return True

    except Exception as e:
        UI.log(
            "No se pudo guardar la base de Capa 2 ({}): {}. "
            "El proceso continua.".format(ruta, e),
            "warn"
        )
        return False


def clave_existente(datos, nombre_capa2):
    """
    Devuelve la llave de la base que corresponde a ese Capa 2.
    Tolera la diferencia '-' vs '_' en el nombre (ej. HAC-MED.X vs HAC_MED.X).
    Si no existe ninguna, devuelve la llave normalizada.
    """
    clave = normalizar_nombre(nombre_capa2)

    if clave in datos:
        return clave

    equivalente = clave.replace("_", "-")

    for k in datos:
        if normalizar_nombre(k).replace("_", "-") == equivalente:
            return k

    return clave


def buscar_ip_historial(datos, nombre_capa2):
    """Devuelve la IP guardada para ese Capa 2, o None."""
    reg = datos.get(clave_existente(datos, nombre_capa2))

    if isinstance(reg, dict) and ip_valida(reg.get("ip")):
        return reg["ip"]

    return None


def registrar_historial(datos, nombre_capa2, tipo_capa2, ip, fuente):
    """Crea o actualiza el registro de un Capa 2 con login exitoso."""
    clave = clave_existente(datos, nombre_capa2)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
    reg = datos.get(clave)

    if isinstance(reg, dict):
        if reg.get("ip") != ip:
            reg["fuente"] = fuente
        reg["ip"] = ip
        reg["tipo"] = tipo_capa2
        reg["ultima"] = ahora
        try:
            reg["veces"] = int(reg.get("veces", 0)) + 1
        except Exception:
            reg["veces"] = 1
    else:
        datos[clave] = {
            "fuente": fuente,
            "ip": ip,
            "nombre": clave,
            "primera": ahora,
            "tipo": tipo_capa2,
            "ultima": ahora,
            "veces": 1,
        }


def pedir_ip_capa2(nombre_capa2, tipo_capa2, motivo=None):
    """Pide la IP del Capa 2 EN LA INTERFAZ (None si cancela)."""
    error = None

    while True:
        ip = UI.preguntar_ip(
            motivo if motivo else "Este Capa 2 no esta en la base.",
            nombre_capa2,
            tipo_capa2,
            error
        )

        if not ip:
            return None

        if ip_valida(ip):
            return ip

        error = "La IP '{}' no es valida. Ejemplo: 172.30.165.202".format(ip)


def login_capa2(ip_capa2, tipo_capa2="ZAC"):
    """Abre SSH al Capa 2 y espera el prompt correspondiente."""
    # HAC entra inicialmente bloqueado con prompt ">".
    # ZAC normalmente entra directamente con "#".
    if tipo_capa2 == "HAC":
        ssh_login(ip_capa2, [">"])
    else:
        ssh_login(ip_capa2, ["#"])
    crt.Sleep(500)


def entrar_capa2(datos, puede_guardar, nombre_capa2, tipo_capa2):
    """
    Resuelve la IP del Capa 2 (base o manual), hace el login y
    alimenta la base SOLO si el login fue exitoso.

    Devuelve la IP usada, o None si el operador cancelo.
    """
    ip = buscar_ip_historial(datos, nombre_capa2)

    if ip:
        origen = "base"
    else:
        origen = "manual"
        ip = pedir_ip_capa2(nombre_capa2, tipo_capa2)

        if not ip:
            return None

    # Desde aqui se debe estar en el jump host (ya se salio del Capa 3)
    salir_capa3()

    while True:
        try:
            login_capa2(ip, tipo_capa2)
            break

        except LoginError as e:
            # Solo se reintenta si el equipo no respondio (IP mala).
            # Una clave rechazada se informa y se aborta.
            if not e.de_red:
                raise

            ip_nueva = pedir_ip_capa2(
                nombre_capa2,
                tipo_capa2,
                "No se pudo conectar a {} ({}):\n{}\n\n"
                "Ingrese la IP correcta o deje vacio para cancelar."
                .format(
                    ip,
                    "guardada en la base" if origen == "base" else "manual",
                    e
                )
            )

            if not ip_nueva:
                raise

            ip = ip_nueva
            origen = "manual"

    # Login exitoso -> alimentar la base
    registrar_historial(datos, nombre_capa2, tipo_capa2, ip, "manual")

    if puede_guardar:
        guardar_historial(datos)

    return ip


def ejecutar_huawei_doble_enter(comando, paginacion="q"):
    """Ejecuta comandos Huawei y maneja la paginacion sin afectar el siguiente comando."""
    crt.Sleep(500)
    crt.Screen.Send(comando + "\r")
    crt.Sleep(800)

    # Algunos comandos Huawei muestran primero el selector interactivo.
    try:
        crt.Screen.ReadString("}:", 3)
        crt.Screen.Send("\r")
        crt.Sleep(800)
    except Exception:
        pass

    salida_total = ""

    while True:
        # Esperamos cualquiera de los dos finales posibles:
        # 1 = aparece la paginacion, 2 = termina el comando y aparece el prompt.
        # Huawei puede mostrar la paginacion como "-- More" o como
        # "-- Press 'Q' to break --". En la tabla de trafico de HAC
        # aparece esta segunda forma; ambas deben tratarse igual.
        bloque = crt.Screen.ReadString(
            ["-- More", "Press 'Q' to break", "#"],
            10
        )
        salida_total += bloque

        if crt.Screen.MatchIndex in (1, 2):
            if paginacion == "espacio":
                # Tabla de trafico: avanzar TODAS las paginas con espacio.
                crt.Screen.Send(" ")
                crt.Sleep(500)
                continue

            # ONT info: salir inmediatamente de la paginacion con q.
            crt.Screen.Send("q")
            crt.Sleep(800)

            # MUY IMPORTANTE: esperar el prompt antes de permitir el siguiente
            # comando. Asi no se pega el siguiente comando al texto anterior.
            try:
                salida_total += crt.Screen.ReadString("#", 5)
            except Exception:
                pass
            break

        # MatchIndex == 2: el comando termino normalmente.
        break

    return salida_total

def obtener_ont_hac(salida_ont):
    """Extrae F/S/P y ONT-ID de display ont info by-sn."""
    fs_p = None
    ont_id = None

    m = re.search(r"F/S/P\s*:\s*(\d+/\d+/\d+)", salida_ont, re.IGNORECASE)
    if m:
        fs_p = m.group(1)

    m = re.search(r"ONT-ID\s*:\s*(\d+)", salida_ont, re.IGNORECASE)
    if m:
        ont_id = m.group(1)

    return fs_p, ont_id


def obtener_service_port_vlan_201(salida_service_port):
    """Encuentra el INDEX de la fila cuya VLAN ID es 201."""
    for linea in salida_service_port.splitlines():
        partes = linea.split()

        # Formato esperado de la tabla:
        # INDEX VLAN-ID VLAN-ATTR PORT-TYPE F/S/P VPI VCI FLOW...
        if len(partes) < 8:
            continue

        if not partes[0].isdigit():
            continue

        if partes[1] != "201":
            continue

        return partes[0]

    return None


def obtener_tids_velocidad(salida_traffic, velocidad):
    """
    Obtiene los TID DOWN/UP reales de la tabla de tráfico de HAC.

    Los TID NO son fijos y cambian según la tabla del equipo.
    La tabla se interpreta por parejas consecutivas:
        TID N     = DOWN
        TID N + 1 = UP

    Para evitar tomar un perfil incorrecto cuando varias velocidades
    comparten el mismo CIR, primero se busca el perfil exacto conocido
    para el DOWN. Si no existe, se acepta cualquier DOWN con el CIR
    esperado y se toma el TID consecutivo como UP.

    El CIR del UP puede ser distinto al CIR del DOWN, por lo que se
    permiten perfiles asimétricos.
    """


    velocidad = str(velocidad).strip()

    if velocidad not in CIR_POR_VELOCIDAD:
        return None, None, None

    cir_objetivo = CIR_POR_VELOCIDAD[velocidad]
    perfil_objetivo = PERFIL_DOWN.get(velocidad)

    filas = []
    patron = re.compile(
        r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+"
    )

    for linea in salida_traffic.splitlines():
        m = patron.match(linea)
        if m:
            filas.append(tuple(map(int, m.groups())))

    filas.sort(key=lambda x: x[0])

    candidatos_cir = []

    for i in range(len(filas) - 1):
        tid_down, cir_down, cbs_down, pir_down, pbs_down = filas[i]
        tid_up = filas[i + 1][0]

        # DOWN y UP deben ser TID consecutivos.
        if tid_up != tid_down + 1:
            continue

        # El DOWN debe corresponder al CIR de la velocidad.
        if cir_down != cir_objetivo:
            continue

        candidatos_cir.append((str(tid_down), str(tid_up)))

        # Prioridad: perfil exacto del DOWN.
        if perfil_objetivo and (
            cir_down,
            cbs_down,
            pir_down,
            pbs_down
        ) == perfil_objetivo:
            return cir_objetivo, str(tid_down), str(tid_up)

    # Fallback: permite perfiles asimétricos.
    # El UP puede tener cualquier CIR porque lo importante es que
    # sea el TID inmediatamente siguiente al DOWN encontrado.
    if candidatos_cir:
        tid_down, tid_up = candidatos_cir[0]
        return cir_objetivo, tid_down, tid_up

    return cir_objetivo, None, None

def construir_descripcion(nombre_usuario, cuenta_rr):
    """Une nombre y RR en el formato solicitado para HAC y ZAC."""
    nombre = str(nombre_usuario).strip().upper()
    nombre = re.sub(r"\s+", "_", nombre)
    nombre = re.sub(r"_+", "_", nombre)
    rr = str(cuenta_rr).strip()
    return "{}_{}".format(nombre, rr)


def configurar_hac(sn_ont, velocidad, ip_capa2, nombre_capa2, bridge="NO", descripcion_cliente=""):
    """Configura velocidad de VLAN 201 en HAC y devuelve un resumen.

    El login al HAC ya lo hizo entrar_capa2() en main.
    """

    # 1. Desbloquear HAC.
    crt.Screen.Send("enable\r")
    crt.Sleep(800)
    crt.Screen.ReadString("#")

    # 2. Buscar ONT por SN y obtener F/S/P + ONT-ID.
    salida_ont = ejecutar_huawei_doble_enter(
        "display ont info by-sn {}".format(sn_ont)
    )

    fs_p, ont_id = obtener_ont_hac(salida_ont)

    if not fs_p or not ont_id:
        raise ProcesoError(
            "No se pudo obtener F/S/P u ONT-ID del HAC.\n\n"
            "SN: {}\n\n"
            "Salida recibida:\n{}".format(sn_ont, salida_ont)
        )

    # 3. Buscar el service-port de la VLAN 201 para esa ONT.
    cmd_service = "display service-port port {} ont {}".format(fs_p, ont_id)
    salida_service = ejecutar_huawei_doble_enter(cmd_service)
    service_port = obtener_service_port_vlan_201(salida_service)

    if not service_port:
        raise ProcesoError(
            "No se encontró un service-port con VLAN 201.\n\n"
            "F/S/P: {}\n"
            "ONT-ID: {}\n\n"
            "Salida recibida:\n{}".format(fs_p, ont_id, salida_service)
        )

    # 4. Consultar tabla de tráfico y localizar TID DOWN/UP.
    salida_traffic = ejecutar_huawei_doble_enter(
        "display traffic table ip from-index 0 | no-more"
    )

    cir, tid_down, tid_up = obtener_tids_velocidad(
        salida_traffic, velocidad
    )

    if not tid_down or not tid_up:
        raise ProcesoError(
            "No se pudo localizar la velocidad {}M en la tabla de tráfico.\n\n"
            "CIR esperado: {}\n\n"
            "Salida recibida:\n{}".format(
                velocidad, cir if cir else "No definido", salida_traffic
            )
        )

    # 5. Aplicar configuración.
    crt.Screen.Send("config\r")
    crt.Sleep(800)
    crt.Screen.ReadString("#")

    cmd_config_hac = (
        "service-port {0} outbound traffic-table index {1} "
        "inbound traffic-table index {2}"
    ).format(service_port, tid_down, tid_up)

    crt.Screen.Send(cmd_config_hac + "\r")
    crt.Sleep(1000)
    crt.Screen.ReadString("#")

    # 6. MARCAR SERVICE-PORT CON NOMBRE + RR.
    cmd_desc_hac = (
        "service-port desc {0} description {1}"
    ).format(service_port, descripcion_cliente)

    crt.Screen.Send(cmd_desc_hac + "\r")
    crt.Sleep(800)
    crt.Screen.ReadString("#")

    # 7. Verificar configuración aplicada.
    salida_verificacion = ejecutar_huawei_doble_enter(
        "display service-port {}".format(service_port)
    )

    # Validación básica de RX/TX y nombres de las tablas.
    esperado_down = "INTERNET-BA-IP-{}M-DOWN".format(velocidad)
    esperado_up = "INTERNET-BA-IP-{}M-UP".format(velocidad)

    verificacion_ok = (
        re.search(r"\bTX\s*:\s*{}\b".format(re.escape(tid_up)), salida_verificacion)
        and re.search(r"\bRX\s*:\s*{}\b".format(re.escape(tid_down)), salida_verificacion)
        and esperado_down in salida_verificacion
        and esperado_up in salida_verificacion
    )

    mensaje = (
        "Configuración HAC completada.\n\n"
        "Capa 2: {}\n"
        "SN: {}\n"
        "F/S/P: {}\n"
        "ONT-ID: {}\n"
        "Service-port VLAN 201: {}\n"
        "Velocidad: {}M\n"
        "CIR: {} kbps\n"
        "DOWN / RX TID: {}\n"
        "UP / TX TID: {}\n\n"
        "Comando ejecutado:\n{}\n\n"
        "Descripción: {}\n"
        "Comando descripción:\n{}\n\n"
        "Verificación: {}\n\n"
        "Salida final:\n{}"
    ).format(
        nombre_capa2,
        sn_ont,
        fs_p,
        ont_id,
        service_port,
        velocidad,
        cir,
        tid_down,
        tid_up,
        cmd_config_hac,
        descripcion_cliente,
        cmd_desc_hac,
        "OK" if verificacion_ok else "REVISAR",
        salida_verificacion,
    )

    # 7. SI BRIDGE = SI, CONFIGURAR NATIVE VLAN 201 EN ETH 4 DE LA ONT.
    #    Los valores se toman OBLIGATORIAMENTE del F/S/P + ONT-ID encontrados.
    cmd_bridge_hac = None
    salida_bridge_hac = None
    salida_bridge_pre = ""

    if bridge == "SI":
        partes_fsp = fs_p.split("/")
        if len(partes_fsp) != 3:
            raise ProcesoError(
                "F/S/P invalido para configurar Bridge.\n\n"
                "F/S/P: {}".format(fs_p)
            )

        frame = partes_fsp[0]
        slot = partes_fsp[1]
        ont_port = partes_fsp[2]

        # Entrar a la GPON exacta obtenida del F/S/P.
        crt.Screen.Send(
            "interface gpon {}/{}\r".format(frame, slot)
        )
        crt.Screen.ReadString("#")

        # Verificar la ONT usando el ONT-port y ONT-ID reales.
        salida_bridge_pre = ejecutar_huawei_doble_enter(
            "display ont port attribute {} {} eth".format(
                ont_port, ont_id
            )
        )

        # Bridge: siempre sobre ETH 4 y VLAN 201.
        cmd_bridge_hac = (
            "ont port native-vlan {} {} eth 4 vlan 201"
        ).format(ont_port, ont_id)

        ejecutar_huawei_doble_enter(cmd_bridge_hac)

        # Verificacion final del puerto ETH 4.
        salida_bridge_hac = ejecutar_huawei_doble_enter(
            "display ont port attribute {} {} eth".format(
                ont_port, ont_id
            )
        )

        # Salir de la interfaz GPON y volver al modo config.
        crt.Screen.Send("quit\r")
        crt.Screen.ReadString("#")

    RES.update({
        "fs_p": fs_p,
        "ont_id": ont_id,
        "service_port": service_port,
        "tid_down": tid_down,
        "tid_up": tid_up,
        "cir": cir,
        "verificacion": "OK" if verificacion_ok else "REVISAR",
        "configurado": True,
        "cmd_velocidad": cmd_config_hac,
        "cmd_descripcion": cmd_desc_hac,
        "cmd_bridge": cmd_bridge_hac or "",
        "comandos_aplicados": [
            c for c in (cmd_config_hac, cmd_desc_hac, cmd_bridge_hac) if c
        ],
        "raw": {
            "salida_ont": salida_ont,
            "salida_service": salida_service,
            "salida_traffic": salida_traffic,
            "bridge_pre": salida_bridge_pre,
            "bridge_post": salida_bridge_hac or "",
            "verificacion": salida_verificacion,
        },
    })
    UI.log("HAC configurado. Service-port {}, verificacion {}".format(
        service_port, "OK" if verificacion_ok else "REVISAR"))

    return {
        "fs_p": fs_p,
        "ont_id": ont_id,
        "service_port": service_port,
        "tid_down": tid_down,
        "tid_up": tid_up,
        "cir": cir,
        "comando": cmd_config_hac,
        "verificacion_ok": bool(verificacion_ok),
        "bridge_comando": cmd_bridge_hac,
        "bridge_salida": salida_bridge_hac,
    }



def obtener_ips_incompletas(salida_arp):
    """Devuelve las IPs cuyo estado de MAC es Incomplete."""

    libres = []

    patron = re.compile(
        r"^(\d{1,3}(?:\.\d{1,3}){3})\s+Incomplete\b"
    )

    for linea in salida_arp.splitlines():

        m = patron.match(linea.strip())

        if m:
            libres.append(m.group(1))

    return libres


def salir_perfil_zac():
    """Sale del perfil ZAC enviando 'q' dos veces."""
    crt.Sleep(500)
    crt.Screen.Send("q\r")
    crt.Sleep(800)

    crt.Screen.Send("q\r")
    crt.Sleep(800)


def salir_perfil_hac():
    """Sale del perfil HAC: quit, luego q, luego y."""
    crt.Sleep(500)
    crt.Screen.Send("quit\r")
    crt.Sleep(800)

    crt.Screen.Send("q\r")
    crt.Sleep(800)

    crt.Screen.Send("y\r")
    crt.Sleep(800)


def reconsultar_ips_libres(ip_capa3, interfaz):
    """
    Vuelve a entrar al Capa 3 real y repite la consulta de IPs
    'Incomplete' sobre la interfaz, para tenerlas a la mano
    justo despues de terminar la configuracion en el Capa 2.
    """
    login_capa3(ip_capa3)

    enviar_y_leer(
        "screen-length 0 temporary",
        ">"
    )

    salida_arp = enviar_y_leer(
        "dis arp int {} | in I".format(interfaz),
        ">"
    )

    ips_libres = obtener_ips_incompletas(salida_arp)

    RES["ips_libres_final"] = ips_libres
    UI.log("IPs libres finales en {}: {}".format(interfaz, len(ips_libres)))

    return ips_libres


def ruta_portal_script():
    if PORTAL_SCRIPT:
        return PORTAL_SCRIPT
    try:
        base = os.path.dirname(crt.ScriptFullName)
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "portal_csr.py")


# Prefijos de SERIAL conocidos (siempre serial).
SERIAL_PREFIJOS = ("ZTE", "SEI", "SDM", "SERC", "SKY", "HWTC", "SCOM", "FHTT", "ALCL", "CIGG", "GPON")


def es_mac(texto):
    """True solo si es una MAC: 12 caracteres hexadecimales (con o sin ':' '-' '.') y sin prefijo de serial.
    Lo demas es serial (ej. SCOMA0B03D18 lleva S, O, M: no es hexadecimal)."""
    t = texto.strip().upper()
    if t.startswith(SERIAL_PREFIJOS):
        return False
    return re.match(r"^[0-9A-F]{12}$", re.sub(r"[:.\-\s]", "", t)) is not None


def solo_ascii(texto):
    """Quita acentos (Ó->O, Ñ->N) y deja solo ASCII. Funciona en Python 2 y 3:
    el Python de SecureCRT es 2.7 y no puede formatear texto con acentos."""
    if not isinstance(texto, type(u"")):
        try:
            texto = texto.decode("utf-8", "replace")
        except Exception:
            return str(texto)
    # SecureCRT no trae el modulo unicodedata: tabla manual de acentos.
    orig = u"\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1\u00c0\u00c8\u00cc\u00d2\u00d9\u00e0\u00e8\u00ec\u00f2\u00f9\u00c2\u00ca\u00ce\u00d4\u00db\u00e2\u00ea\u00ee\u00f4\u00fb\u00c7\u00e7"
    dest = u"AEIOUUNaeiouunAEIOUaeiouAEIOUaeiouCc"
    out = []
    for ch in texto:
        i = orig.find(ch)
        if i >= 0:
            out.append(dest[i])
        elif ord(ch) < 128:
            out.append(ch)
    t = u"".join(out)
    return t.encode("ascii") if str is bytes else t


def consultar_portal(modo, valor):
    """Llama a portal_csr.py y devuelve el dict del portal (o lanza Exception)."""
    ruta = ruta_portal_script()

    if not os.path.exists(ruta):
        raise Exception("No existe {}".format(ruta))

    cargar_credenciales()
    if not PORTAL_USUARIO or not PORTAL_CLAVE:
        raise Exception("Faltan el usuario o la clave del Support Portal. Escribalos en la interfaz: "
                        "Ajustes > Support Portal (se guardan cifrados en su PC).")

    env = os.environ.copy()
    env["PORTAL_USER"] = PORTAL_USUARIO
    if PORTAL_CLAVE:
        env["PORTAL_PASS"] = PORTAL_CLAVE

    flags = 0x08000000 if os.name == "nt" else 0

    p = subprocess.Popen(
        [PYTHON_EXE, ruta, "--modo", modo, "--valor", valor, "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=flags
    )
    out, err = p.communicate()
    out = out.decode("utf-8", "replace").strip()
    err = err.decode("utf-8", "replace").strip()

    linea = out.splitlines()[-1] if out else ""

    try:
        datos = json.loads(linea)
    except Exception:
        raise Exception("Respuesta invalida del portal.\n\n{}\n{}".format(out, err))

    if not datos.get("ok"):
        raise Exception(solo_ascii(datos.get("error", "Error desconocido")))

    # Texto del portal sin acentos (los equipos no los aceptan y Python 2 falla al formatearlos)
    for k in list(datos.keys()):
        if k != "crudo" and isinstance(datos[k], (type(u""), str)):
            datos[k] = solo_ascii(datos[k])

    return datos


def pedir_datos_ont():
    """
    Espera los datos en la interfaz (SERIAL/MAC, MEGAS, BRIDGE) y consulta
    el portal. Devuelve (ont_ip, sn_ont, velocidad, bridge, nombre, cuenta_rr)
    o None si el operador cerro la ventana sin iniciar.
    """
    sol = UI.esperar_solicitud()

    if not sol:
        return None

    valor = solo_ascii(sol.get("valor", "") or "").strip()
    velocidad = solo_ascii(sol.get("megas", "") or "").strip()
    bridge = solo_ascii(sol.get("bridge", "NO") or "NO").strip().upper()

    if not solo_ascii(sol.get("solicitud_id", "") or "").strip():
        raise ProcesoError("Falta la solicitud: peguela en la interfaz (SOLICITUD ID y CUENTA RR).")

    if not valor:
        raise ProcesoError("No se indico el serial o la MAC.")

    if not velocidad.isdigit():
        raise ProcesoError("La velocidad debe ser un numero entero. Ejemplo: 950")

    if bridge not in ("SI", "NO"):
        raise ProcesoError("El dato Bridge debe ser solamente SI o NO.")

    modo = "mac" if es_mac(valor) else "serial"

    if modo == "mac":
        # 30F947BC76F2 -> 30:f9:47:bc:76:f2 (formato que muestra el portal)
        h = re.sub(r"[^0-9A-Fa-f]", "", valor)
        if len(h) == 12:
            valor = ":".join(h[i:i + 2] for i in range(0, 12, 2)).lower()

    UI.paso(1, "Consultando el Support Portal ({})".format(modo.upper()))

    try:
        r = consultar_portal(modo, valor)
    except Exception as e:
        raise ProcesoError("No se pudo consultar el portal: {}".format(e))

    ont_ip = r.get("ip", "")
    sn_ont = r.get("serial", "")
    nombre = r.get("cliente", "")
    rr = r.get("cuenta_rr", "")

    if not ip_valida(ont_ip) or not sn_ont or not nombre or not rr:
        raise ProcesoError(
            "El portal respondio con datos incompletos. IP: {} | Serial: {} | "
            "Cliente: {} | RR (mycust04): {}".format(ont_ip, sn_ont, nombre, rr)
        )

    RES.update({
        "cliente": nombre,
        "rr": rr,
        "serial": sn_ont,
        "mac": r.get("mac", ""),
        "ip_ont": ont_ip,
        "fabricante": r.get("fabricante", ""),
        "modelo": r.get("product_class", ""),
        "ubicacion": r.get("ubicacion", ""),
        "velocidad": velocidad,
        "bridge": bridge,
        "portal": r,
        "solicitud_id": solo_ascii(sol.get("solicitud_id", "") or "").strip(),
        "txt_sol": sol.get("txt_sol", "") or "",  # sin str(): Python 2 falla con acentos
    })

    UI.log("Portal: {} / RR {} / IP ONT {}".format(nombre, rr, ont_ip))

    return ont_ip, sn_ont, velocidad, bridge, nombre, rr


def main_proceso():

    crt.Screen.Synchronous = True

    # ========================================================
    # 1. SERIAL o MAC -> el Support Portal entrega IP ONT, SN, cliente y RR
    # ========================================================

    resultado = pedir_datos_ont()

    if not resultado:
        return

    ont_ip, sn_ont, velocidad, bridge, nombre_usuario, cuenta_rr = resultado

    descripcion_cliente = construir_descripcion(
        nombre_usuario,
        cuenta_rr
    )

    RES["descripcion"] = descripcion_cliente

    # ========================================================
    # 2. INGRESAR AL A9KTRIARA2
    # ========================================================

    UI.paso(2, "Entrando al A9K y descubriendo el Capa 3")

    prompt_a9k = login_a9k()

    # ========================================================
    # 3. DESCUBRIR EL CAPA 3 REAL MEDIANTE BGP
    # ========================================================

    cmd_bgp = (
        "sho bgp vpnv4 unicast rd 100:15604 {}"
    ).format(ont_ip)

    crt.Sleep(800)
    crt.Screen.Send(cmd_bgp + "\r")

    # IMPORTANTE:
    # La salida BGP contiene:
    #
    #   Paths: (1 available, best #1)
    #
    # Por eso NO usamos "#" como delimitador.
    #
    # Esperamos primero el eco completo del comando.
    crt.Screen.ReadString(cmd_bgp)

    crt.Sleep(2500)

    # El prompt del A9K inicial es conocido:
    #
    # RP/0/RSP0/CPU0:A9KTRIARA2#
    #
    # Esperamos el prompt COMPLETO para que "#1" dentro de
    # "best #1" no corte la lectura.
    prompt_a9k_completo = (
        "RP/0/RSP0/CPU0:{}#"
    ).format(CAPA3_INICIAL)

    salida_bgp = crt.Screen.ReadString(
        prompt_a9k_completo
    )

    ip_capa3 = obtener_capa3_desde_bgp(
        salida_bgp
    )

    if not ip_capa3:

        raise ProcesoError(
            "No se pudo identificar la IP del Capa 3 "
            "desde la salida BGP.\n\n"
            "Comando ejecutado:\n{}\n\n"
            "Salida recibida:\n{}"
            .format(cmd_bgp, salida_bgp)
        )

    RES["capa3_inicial"] = CAPA3_INICIAL
    RES["capa3"] = ip_capa3
    UI.paso(3, "Leyendo ruta, interfaz y Capa 2")

    # 4. SALIR DEL A9KTRIARA2
    # ========================================================

    salir_a9k()

    # ========================================================
    # 5. INGRESAR AL CAPA 3 REAL
    # ========================================================

    login_capa3(ip_capa3)

    # ========================================================
    # 6. PROCESO ORIGINAL DEL CAPA 3
    # ========================================================

    enviar_y_leer(
        "screen-length 0 temporary",
        ">"
    )

    cmd_ruta = (
        "display ip routing-table vpn-instance {} {}"
    ).format(VRF, ont_ip)

    salida_ruta = enviar_y_leer(
        cmd_ruta,
        ">"
    )

    interfaz_bruta = obtener_interfaz(
        salida_ruta
    )

    datos_ruta = obtener_datos_ruta(salida_ruta)
    gateway = datos_ruta["gateway"] if datos_ruta else None
    destination_mask = datos_ruta["destination_mask"] if datos_ruta else None

    if not interfaz_bruta:

        raise ProcesoError(
            "No se pudo identificar la interfaz "
            "en la tabla de ruteo.\n\n"
            "IP ONT: {}\n"
            "Capa 3 descubierto: {}\n\n"
            "Salida recibida:\n{}"
            .format(
                ont_ip,
                ip_capa3,
                salida_ruta
            )
        )

    interfaz = forzar_sufijo_201(
        interfaz_bruta
    )

    if not interfaz:

        raise ProcesoError("Se obtuvo una interfaz vacia.")

    # ========================================================
    # 7. OBTENER CAPA 2
    # ========================================================

    salida_config = enviar_y_leer(
        "dis cur int {}".format(interfaz),
        ">"
    )

    tipo_capa2, nombre_capa2 = obtener_capa2(
        salida_config
    )

    gateway, mascara = obtener_ip_y_mascara_interfaz(
        salida_config
    )

    if nombre_capa2:

        # Copiar exactamente el bloque de configuracion de la interfaz,
        # incluyendo interface, description, ip address, etc.
        bloque_interfaz = salida_config.strip()

        copiar_al_portapapeles(
            bloque_interfaz
        )

    else:

        UI.log(
            "ATENCION: no se pudo extraer el Capa 2 de la descripcion. "
            "Salida: {}".format(salida_config),
            "warn"
        )

    # ========================================================
    # 8. BUSCAR IPS INCOMPLETAS
    # ========================================================

    RES.update({
        "interfaz_encontrada": interfaz_bruta,
        "bloque_interfaz": salida_config.strip(),
        "interfaz": interfaz,
        "capa2": nombre_capa2 if nombre_capa2 else "No identificado",
        "tipo_capa2": tipo_capa2 if tipo_capa2 else "N/A",
        "gateway": gateway if gateway else "",
        "mascara": mascara if mascara else "",
        "destination_mask": destination_mask if destination_mask else "",
    })

    UI.paso(4, "Buscando IPs libres")

    salida_arp = enviar_y_leer(
        "dis arp int {} | in I".format(interfaz),
        ">"
    )

    ips_libres = obtener_ips_incompletas(
        salida_arp
    )

    RES["ips_libres"] = ips_libres

    UI.log("IPs libres encontradas: {}".format(len(ips_libres)))

    # ========================================================
    # PROPIEDAD RED ONNET / ATP: SOLO se consultan las IPs disponibles.
    # No se entra al Capa 2 ni se configura nada.
    # ========================================================
    _m = re.search(r"PROPIEDAD RED:[ \t]*(.*)", RES.get("txt_sol", "") or "", re.I)
    _prop = (_m.group(1) if _m else "").upper()

    if "ONNET" in _prop or "ATP" in _prop:
        RES["solo_consulta"] = True
        RES["nota"] = (
            "Red {}: solo consulta de IPs disponibles ({} libres). "
            "No se configura el Capa 2.".format(_prop.strip(), len(ips_libres))
        )
        UI.log(RES["nota"])
        return

    # (Se elimino el "q" que se enviaba aqui: en Huawei "q" = quit y
    #  cerraba el Capa 3 antes de tiempo. La salida la hace salir_capa3.)

    # ========================================================
    # 10. SI ES HAC O ZAC: IP DEL CAPA 2 DESDE LA BASE (historial_capa2.json)
    #     Si el Capa 2 esta en la base, el login es automatico.
    #     Si no esta, se pide la IP manual y, tras un login exitoso,
    #     se guarda en la base para la proxima vez.
    #
    #     entrar_capa2() sale del Capa 3 (queda en el jump host),
    #     hace el ssh al Capa 2 y deja la sesion lista.
    # ========================================================
    nombre_capa2_upper = (nombre_capa2 or "").upper()

    ip_capa2 = None

    # Si es HAC y la velocidad no existe en la tabla, se avisa ANTES de
    # entrar al Capa 2 (evita hacer login para fallar al final).
    if tipo_capa2 == "HAC" and velocidad not in CIR_POR_VELOCIDAD:

        raise ProcesoError(
            "La velocidad {}M no esta soportada en HAC.\n\n"
            "Velocidades soportadas:\n{}".format(
                velocidad,
                ", ".join(sorted(CIR_POR_VELOCIDAD, key=int))
            )
        )

    if tipo_capa2 in ("HAC", "ZAC"):

        UI.paso(5, "Entrando al Capa 2")

        historial, puede_guardar = cargar_historial()

        ip_capa2 = entrar_capa2(
            historial,
            puede_guardar,
            nombre_capa2,
            tipo_capa2
        )

        if not ip_capa2:
            raise ProcesoError(
                "No se indico la IP del Capa 2; proceso detenido."
            )

        RES["ip_capa2"] = ip_capa2

    if tipo_capa2 == "HAC":

        UI.paso(6, "Configurando velocidad y descripcion (HAC)")

        # Aqui comienza el nuevo proceso HAC usando la misma ONT/SN
        # y la velocidad indicada al inicio.
        configurar_hac(
            sn_ont,
            velocidad,
            ip_capa2,
            nombre_capa2 if nombre_capa2 else "HAC",
            bridge,
            descripcion_cliente
        )

        # ========================================================
        # SALIR DEL HAC Y RE-CONSULTAR IPS LIBRES EN EL CAPA 3
        # ========================================================
        UI.paso(7, "Verificando y cerrando")

        salir_perfil_hac()
        reconsultar_ips_libres(ip_capa3, interfaz)

        return

    # OH, ATP u otros Capa 2 que no tengan flujo HAC/ZAC terminan aqui.
    if (
        tipo_capa2 == "OH"
        or nombre_capa2_upper.startswith("OH-")
        or ".ATP" in nombre_capa2_upper
        or "ONNET" in nombre_capa2_upper
        or ".ONNET" in nombre_capa2_upper
    ):
        # La consulta "dis cur int ..." ya fue copiada al portapapeles.
        # ATP/ONNET: detener aqui y no ejecutar configuracion.
        RES["nota"] = (
            "Capa 2 OH/ATP/ONNET: no hay configuracion automatica. "
            "El bloque de la interfaz se copio al portapapeles."
        )
        return

    # Si no es ZAC, termina
    if tipo_capa2 != "ZAC":
        return

    # ========================================================
    # 11. LOGIN AL CAPA 2 ZAC
    #     (el login ya lo hizo entrar_capa2() en el paso 10)
    # ========================================================

    # ========================================================
    # 12. BUSCAR ONT POR SN
    # ========================================================

    UI.paso(6, "Configurando velocidad y descripcion (ZAC)")

    sn_ont = sn_ont.strip()

    cmd_gpon = "sh gpon onu by sn {}".format(sn_ont)

    crt.Screen.Send(cmd_gpon + "\r")

    crt.Sleep(3000)

    # La salida de "sh gpon onu by sn" puede quedar repartida en pantalla.
    # Capturamos primero la salida normal hasta el prompt y, si no aparece
    # la GPON completa, tomamos el contenido visible de la pantalla.
    texto_pantalla = ""
    try:
        texto_pantalla = crt.Screen.ReadString("#", 10)
    except Exception:
        pass

    m_gpon = re.search(
        r"gpon_onu\s*-\s*(\d+/\d+/\d+)\s*:\s*(\d+)",
        texto_pantalla,
        re.IGNORECASE
    )

    # Fallback: buscar directamente en el contenido visible de SecureCRT.
    if not m_gpon:
        try:
            filas = crt.Screen.Rows
            columnas = crt.Screen.Columns
            visible = crt.Screen.Get(1, 1, filas, columnas)
        except Exception:
            visible = ""

        texto_pantalla = (texto_pantalla or "") + "\n" + (visible or "")

        m_gpon = re.search(
            r"gpon_onu\s*-\s*(\d+/\d+/\d+)\s*:\s*(\d+)",
            texto_pantalla,
            re.IGNORECASE
        )

    if not m_gpon:

        raise ProcesoError(
            "No se pudo identificar la interfaz GPON.\n\n"
            "Debe aparecer algo como: "
            "gpon_onu-1/2/15:18\n\n"
            "SN consultado: {}\n\n"
            "Salida visible:\n{}"
            .format(
                sn_ont,
                texto_pantalla
            )
        )

    gpon_base = m_gpon.group(1)
    onu_id = m_gpon.group(2)

    vport = "{}.{}:1".format(
        gpon_base,
        onu_id
    )

    # ========================================================
    # 13. CONSULTAR CONFIGURACION ACTUAL
    # ========================================================

    cmd_running = (
        "sh running-config-interface vport-{}"
    ).format(vport)

    crt.Screen.Send(cmd_running + "\r")

    salida_running = crt.Screen.ReadString("#")

    # Consulta extra de SOLO LECTURA: estado previo de la GPON (name /
    # description / vlan port) para la evidencia PREVIA de la plantilla.
    crt.Screen.Send(
        "sh running-config-interface gpon_onu-{}:{}\r".format(gpon_base, onu_id)
    )
    salida_gpon_pre = crt.Screen.ReadString("#")

    # ========================================================
    # 14. GENERAR CONFIGURACION
    # ========================================================

    cmd_config = (
        "service-port 5 user-vlan 201 vlan 201 "
        "ingress INTERNET-BA-IP-{0}M-UP "
        "egress INTERNET-BA-IP-{0}M-DOWN"
    ).format(velocidad)

    # ========================================================
    # 15. APLICAR CAMBIO EN VPORT
    # ========================================================

    crt.Screen.Send("conf t\r")
    crt.Screen.ReadString("#")

    crt.Screen.Send(
        "interface vport-{}\r".format(vport)
    )
    crt.Screen.ReadString("#")

    crt.Screen.Send(cmd_config + "\r")
    crt.Screen.ReadString("#")

    # ========================================================
    # 16. SI BRIDGE = SI, AGREGAR SECURITY MAX-MAC-LEARN 5
    # ========================================================

    cmd_security = "security max-mac-learn 5"

    if bridge == "SI":
        crt.Screen.Send(cmd_security + "\r")
        crt.Screen.ReadString("#")

    # ========================================================
    # 17. SALIR DOS VECES DEL VPORT / CONFIG
    # ========================================================

    crt.Screen.Send("exit\r")
    crt.Screen.ReadString("#")

    crt.Screen.Send("exit\r")
    crt.Screen.ReadString("#")

    # ========================================================
    # 18. SI BRIDGE = SI, CONFIGURAR BRIDGE EN LA GPON
    # ========================================================

    if bridge == "SI":

        # Se construye con la GPON encontrada automaticamente
        # mediante el SN. Ejemplo: gpon_onu-1/1/1:9
        gpon_onu = "gpon_onu-{}:{}".format(
            gpon_base,
            onu_id
        )

        # Consulta inicial de la GPON
        cmd_gpon_running = (
            "sh running-config-interface {}"
        ).format(gpon_onu)

        crt.Screen.Send(
            cmd_gpon_running + "\r"
        )

        salida_gpon_running = crt.Screen.ReadString("#")

        # Entrar a configuracion
        crt.Screen.Send("conf t\r")
        crt.Screen.ReadString("#")

        # Entrar al pon-onu-mng de esta ONT
        crt.Screen.Send(
            "pon-onu-mng {}\r".format(gpon_onu)
        )
        crt.Screen.ReadString("#")

        # Habilitar Bridge
        cmd_bridge = (
            "vlan port eth_0/4 mode hybrid def-vlan 201"
        )

        crt.Screen.Send(
            cmd_bridge + "\r"
        )
        crt.Screen.ReadString("#")

        # Salir del pon-onu-mng y de configuracion
        crt.Screen.Send("exit\r")
        crt.Screen.ReadString("#")

        crt.Screen.Send("exit\r")
        crt.Screen.ReadString("#")

        # Consultar nuevamente la GPON
        crt.Screen.Send(
            cmd_gpon_running + "\r"
        )

        salida_gpon_running2 = crt.Screen.ReadString("#")

    # ========================================================
    # 19. MARCAR LA ONT CON NOMBRE + RR
    # ========================================================

    gpon_onu = "gpon_onu-{}:{}".format(
        gpon_base,
        onu_id
    )

    crt.Screen.Send("conf t\r")
    crt.Screen.ReadString("#")

    crt.Screen.Send(
        "interface {}\r".format(gpon_onu)
    )
    crt.Screen.ReadString("#")

    cmd_name_zac = "name {}".format(descripcion_cliente)
    crt.Screen.Send(cmd_name_zac + "\r")
    crt.Screen.ReadString("#")

    cmd_description_zac = "description {}".format(descripcion_cliente)
    crt.Screen.Send(cmd_description_zac + "\r")
    crt.Screen.ReadString("#")

    crt.Screen.Send("exit\r")
    crt.Screen.ReadString("#")
    crt.Screen.Send("exit\r")
    crt.Screen.ReadString("#")

    # Verificar nombre y descripción de la ONT.
    cmd_gpon_nombre_verificacion = (
        "sh running-config-interface {}"
    ).format(gpon_onu)

    crt.Screen.Send(cmd_gpon_nombre_verificacion + "\r")
    salida_gpon_nombre = crt.Screen.ReadString("#")

    # ========================================================
    # 19. CONSULTA FINAL DEL VPORT
    # ========================================================

    cmd_running2 = (
        "sh running-config-interface vport-{}"
    ).format(vport)

    crt.Screen.Send(
        cmd_running2 + "\r"
    )

    salida_running2 = crt.Screen.ReadString("#")

    # ========================================================
    # 20. RESULTADO FINAL
    # ========================================================

    UI.paso(7, "Verificando y cerrando")

    RES.update({
        "gpon": "gpon_onu-{}:{}".format(gpon_base, onu_id),
        "vport": vport,
        "comando_velocidad": cmd_config,
        "verificacion": "Configuracion final consultada",
        "configurado": True,
        "cmd_config": cmd_config,
        "cmd_security": cmd_security if bridge == "SI" else "",
        "cmd_bridge": cmd_bridge if bridge == "SI" else "",
        "comandos_aplicados": [
            c for c in (
                cmd_config,
                cmd_security if bridge == "SI" else "",
                cmd_bridge if bridge == "SI" else "",
                cmd_name_zac,
                cmd_description_zac,
            ) if c
        ],
        "raw": {
            "gpon_pre": salida_gpon_pre,
            "vport_pre": salida_running,
            "gpon_post": salida_gpon_nombre,
            "vport_post": salida_running2,
            "gpon_bridge_post": salida_gpon_running2 if bridge == "SI" else "",
        },
    })
    UI.log("ZAC configurado: {} / vport {}".format(RES["gpon"], vport))

    # ========================================================
    # SALIR DEL ZAC Y RE-CONSULTAR IPS LIBRES EN EL CAPA 3
    # ========================================================
    salir_perfil_zac()
    reconsultar_ips_libres(ip_capa3, interfaz)


def lanzar_gui(carpeta):
    """Abre hac_zac_gui.py con el Python del sistema. Devuelve el proceso."""
    ruta = GUI_SCRIPT

    if not ruta:
        try:
            base = os.path.dirname(crt.ScriptFullName)
        except Exception:
            base = os.path.dirname(os.path.abspath(__file__))
        ruta = os.path.join(base, "hac_zac_gui.py")

    if not os.path.exists(ruta):
        raise Exception("No existe la interfaz: {}".format(ruta))

    flags = 0x08000000 if os.name == "nt" else 0

    return subprocess.Popen(
        [PYTHON_EXE, ruta, "--dir", carpeta],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags
    )


def _a_str(v):
    """Python 2: SecureCRT necesita str, no unicode."""
    if str is bytes and isinstance(v, type(u"")):
        return v.encode("utf-8")
    return v


def _carpeta_script():
    try:
        return os.path.dirname(crt.ScriptFullName)
    except Exception:
        return os.path.dirname(os.path.abspath(__file__))


def resolver_python():
    """Python 3 para la interfaz y el portal: el que trae el instalador (carpeta 'python' junto al script); si no
    esta, el de PYTHON_EXE (por defecto 'python' del sistema)."""
    incluido = os.path.join(_carpeta_script(), "python", "python.exe")
    if PYTHON_EXE == "python" and os.path.isfile(incluido):
        return incluido
    return PYTHON_EXE


def _descifrar(valor):
    """Las claves vienen cifradas con DPAPI ('dpapi:...'). Se intenta aqui (ctypes); si el Python de SecureCRT
    no trae ctypes, se le pide a Python 3 (PYTHON_EXE) que la descifre."""
    if not valor or not valor.startswith("dpapi:"):
        return valor
    base = _carpeta_script()
    try:
        import sys
        if base not in sys.path:
            sys.path.insert(0, base)
        import hac_zac_dpapi
        return hac_zac_dpapi.descifrar(valor)
    except Exception:
        pass
    flags = 0x08000000 if os.name == "nt" else 0
    p = subprocess.Popen(
        [PYTHON_EXE, "-c", "import sys,hac_zac_dpapi as d;sys.stdout.write(d.descifrar(sys.stdin.read().strip()))"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=base, creationflags=flags)
    out, err = p.communicate(valor.encode("ascii") if not isinstance(valor, bytes) else valor)
    if p.returncode != 0:
        raise Exception("No se pudo descifrar una clave de Ajustes. Vuelva a escribirla en la interfaz.")
    return out.decode("utf-8")


def cargar_credenciales():
    """Lee credenciales.json (lo guarda la interfaz, pestana Ajustes) y descifra las claves.
    Se llama al abrir y antes de cada conexion, asi lo que se cambie en Ajustes se usa enseguida."""
    global USUARIO, CLAVE, PORTAL_USUARIO, PORTAL_CLAVE
    ruta = os.environ.get("HAC_ZAC_DATOS") or _carpeta_script()
    try:
        with open(os.path.join(ruta, "credenciales.json"), "rb") as f:
            datos = json.loads(f.read().decode("utf-8"))
    except Exception:
        return
    if datos.get("crt_usuario"):
        USUARIO = _a_str(datos["crt_usuario"])
    if datos.get("crt_clave"):
        CLAVE = _a_str(_descifrar(datos["crt_clave"]))
    if datos.get("portal_usuario"):
        PORTAL_USUARIO = _a_str(datos["portal_usuario"])
    if datos.get("portal_clave"):
        PORTAL_CLAVE = _a_str(_descifrar(datos["portal_clave"]))


def main():
    global UI, PYTHON_EXE

    PYTHON_EXE = resolver_python()
    cargar_credenciales()

    carpeta = tempfile.mkdtemp(prefix="hac_zac_")
    UI = Ui(carpeta)

    try:
        UI.proc = lanzar_gui(carpeta)
    except Exception as e:
        # Unico aviso fuera de la interfaz: sin interfaz no hay donde mostrar nada.
        crt.Dialog.MessageBox(
            "No se pudo abrir la interfaz:\n\n{}\n\n"
            "Revise PYTHON_EXE y que hac_zac_gui.py este junto al script."
            .format(e)
        )
        return

    # Si la interfaz muere al arrancar (p. ej. falta tkinter), se avisa.
    crt.Sleep(1500)
    if UI.proc.poll() is not None:
        err = UI.proc.stderr.read().decode("utf-8", "replace")
        crt.Dialog.MessageBox("La interfaz se cerro al iniciar:\n\n{}".format(err))
        return

    if not esperar_jump_host(abortar=lambda: os.path.exists(UI._ruta("solicitud.json"))):
        UI.log("ATENCION: la pestana de SecureCRT no esta conectada al jump host. Conectela antes de iniciar "
               "una solicitud.", "warn")
    recordar_jump_host()

    while True:
        try:
            main_proceso()
            if UI.fase != "esperando":
                UI.fin(RES)
        except Cancelado:
            UI.cancelado()
        except LoginError as e:
            UI.fallo("ERROR DE LOGIN\n\n{}".format(e))
        except ProcesoError as e:
            UI.fallo(e)
        except Exception as e:
            UI.fallo("Error inesperado: {}".format(e))

        # Terminado (bien o mal): volver al jump host y quedar listo para otra solicitud.
        if not UI.gui_viva():
            break
        volver_al_jump_host()
        if not UI.nuevo_ciclo():
            break


main()
