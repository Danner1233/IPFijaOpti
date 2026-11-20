# -*- coding: utf-8 -*-
"""Abre Chrome (visible, con la sesion guardada) de forma robusta para los lectores.

Si Chrome "se cae" al arrancar:
  1) cierra procesos que quedaron colgados con ESTE perfil (no toca su Chrome normal) y borra bloqueos;
  2) reintenta con opciones de compatibilidad;
  3) si el perfil esta danado, usa uno nuevo (habra que iniciar sesion otra vez);
  4) como ultimo recurso abre Microsoft Edge (viene con Windows).
Con «Ver navegador» apagado en Ajustes queda fuera de la pantalla y sin boton en la barra de tareas; vuelve solo
cuando hay que iniciar sesion (aplicar_visibilidad con forzar=True).
"""
import glob
import json
import os
import shutil
import subprocess
import time


def _liberar_perfil(perfil):
    """Mata chromedriver colgado y los chrome que usan este perfil; quita archivos de bloqueo."""
    if os.name == "nt":
        flags = 0x08000000  # CREATE_NO_WINDOW
        marca = os.path.basename(perfil)
        ps = ("Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
              "Where-Object { $_.CommandLine -like '*%s*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % marca)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=flags)
    else:
        subprocess.run(["pkill", "-f", os.path.basename(perfil)], capture_output=True)
    time.sleep(1.5)
    for nombre in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile", "DevToolsActivePort"):
        for f in glob.glob(os.path.join(perfil, nombre)):
            try:
                os.remove(f)
            except OSError:
                pass


def _opciones(clase, perfil, ancho, compat, extra=(), headless=False):
    from selenium import webdriver  # noqa: F401
    o = clase()
    o.add_argument("--user-data-dir=" + perfil)
    o.add_argument("--no-first-run")
    o.add_argument("--no-default-browser-check")
    o.add_argument("--window-size=%s" % ancho)
    o.add_argument("--disable-features=msEdgeSidebarV2,RendererCodeIntegrity")
    # oculto (fuera de pantalla / sin barra de tareas) debe seguir trabajando a ritmo normal
    o.add_argument("--disable-backgrounding-occluded-windows")
    o.add_argument("--disable-renderer-backgrounding")
    o.add_argument("--disable-background-timer-throttling")
    if compat:
        o.add_argument("--disable-gpu")
        o.add_argument("--disable-dev-shm-usage")
        o.add_argument("--no-sandbox")
        o.add_argument("--disable-extensions")
    for x in extra:
        o.add_argument(x)
    if headless:
        o.add_argument("--headless=new")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    return o


def _temp_propio():
    """chromedriver crea carpetas temporales; si TEMP no sirve (OneDrive/permisos) falla con 'cannot create temp
    dir'. Se usa una carpeta propia fuera de OneDrive."""
    base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "tmp")
    try:
        os.makedirs(base, exist_ok=True)
        os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = base
    except OSError:
        pass


FUERA = (-32000, -32000)       # posicion fuera de la pantalla: el navegador sigue trabajando, pero no se ve
DENTRO = (40, 40)


def ver_navegador(proceso):
    """Ajustes > 'ver_<proceso>' (sp, correo, portal). Por defecto SE VE."""
    try:
        from hac_zac.rutas import data_dir
        datos = json.loads((data_dir() / "ajustes.json").read_text(encoding="utf-8"))
        return bool(datos.get("ver_" + proceso, True))
    except Exception:
        return True


def aplicar_visibilidad(driver, proceso, forzar=None):
    """Muestra u oculta la ventana (sin cerrarla) segun el ajuste; se llama en cada vuelta del lector, asi el
    cambio se nota en segundos. `forzar=True` la muestra (p. ej. si hace falta escribir algo en ella).
    Oculta = fuera de la pantalla Y sin boton en la barra de tareas (sigue trabajando normal)."""
    ver = ver_navegador(proceso) if forzar is None else bool(forzar)
    if getattr(driver, "_hz_ver", None) != ver:
        try:
            x, y = DENTRO if ver else FUERA
            driver.set_window_position(x, y)
            driver._hz_ver = ver
        except Exception:
            pass
    if getattr(driver, "_hz_barra", None) != ver:
        if barra_de_tareas(driver, ver):
            driver._hz_barra = ver


# ---------------------------------------------------------------------------------------------- barra de tareas
WS_EX_TOOLWINDOW = 0x00000080     # ventana de herramienta: sin boton en la barra de tareas ni en Alt+Tab
WS_EX_APPWINDOW = 0x00040000
GWL_EXSTYLE = -20


def estilo_barra(estilo, ver):
    """Estilo extendido de la ventana para mostrarla (con boton en la barra) u ocultarla (sin boton)."""
    if ver:
        return (estilo & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    return (estilo | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW


def descendientes(raiz, pares):
    """PIDs de `raiz` y todos sus hijos/nietos; pares = [(pid, pid_padre)]."""
    hijos = {}
    for pid, padre in pares:
        hijos.setdefault(padre, []).append(pid)
    out, pila = set(), [raiz]
    while pila:
        p = pila.pop()
        if p in out:
            continue
        out.add(p)
        pila.extend(hijos.get(p, []))
    return out


def _procesos():
    """[(pid, pid_padre)] de Windows (Toolhelp32, sin dependencias)."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)               # TH32CS_SNAPPROCESS
    out = []
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def _ventanas_de(pids):
    """Ventanas principales (visibles, de primer nivel) de esos procesos."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, 4):   # 4 = GW_OWNER
            clase = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, clase, 64)
            if clase.value.startswith("Chrome_WidgetWin"):
                out.append(hwnd)
        return True
    u.EnumWindows(cada, 0)
    return out


def barra_de_tareas(driver, ver):
    """Quita (ver=False) o devuelve (ver=True) el boton del navegador en la barra de tareas. True si lo aplico.
    Nunca lanza error: si no se puede, el navegador solo queda fuera de la pantalla como antes."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        u = ctypes.windll.user32
        raiz = driver.service.process.pid                     # chromedriver -> chrome.exe (hijos)
        hwnds = _ventanas_de(descendientes(raiz, _procesos()) - {raiz})
        if not hwnds:
            return False
        leer = getattr(u, "GetWindowLongPtrW", u.GetWindowLongW)
        poner = getattr(u, "SetWindowLongPtrW", u.SetWindowLongW)
        leer.restype = poner.restype = ctypes.c_ssize_t
        poner.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        leer.argtypes = (ctypes.c_void_p, ctypes.c_int)
        for h in hwnds:
            u.ShowWindow(h, 0)                                # SW_HIDE: la barra solo se entera al volver a mostrar
            poner(h, GWL_EXSTYLE, estilo_barra(leer(h, GWL_EXSTYLE), ver))
            u.ShowWindow(h, 5 if ver else 4)                  # SW_SHOW / SW_SHOWNOACTIVATE (sigue fuera de pantalla)
            if ver:
                u.SetForegroundWindow(h)
        return True
    except Exception:
        return False


def _msg(e, n=3):
    return " | ".join(l.strip() for l in str(e).strip().splitlines()[:n] if l.strip())


def abrir_navegador(perfil, ancho="1300,850", log=print, extra=(), headless=False, proceso=None):
    """`proceso` (sp / correo / portal) aplica la opcion Ver navegador de Ajustes."""
    from selenium import webdriver
    _temp_propio()
    if proceso and not ver_navegador(proceso):
        extra = tuple(extra) + ("--window-position=%d,%d" % FUERA,)
    nuevo = perfil + "_nuevo"
    if os.path.isdir(nuevo):          # un perfil de reemplazo creado antes pasa a ser el activo
        perfil = nuevo
    os.makedirs(perfil, exist_ok=True)
    errores = []
    intentos = [
        ("Chrome", webdriver.Chrome, webdriver.ChromeOptions, perfil, False),
        ("Chrome (modo compatible)", webdriver.Chrome, webdriver.ChromeOptions, perfil, True),
    ]
    for nombre, drv, opt, p, compat in intentos:
        _liberar_perfil(perfil)
        try:
            d = drv(options=_opciones(opt, p, ancho, compat, extra, headless))
            if proceso:
                d._hz_ver = ver_navegador(proceso)
                aplicar_visibilidad(d, proceso)          # oculto: tambien fuera de la barra de tareas
            return d
        except Exception as e:
            errores.append("%s: %s" % (nombre, _msg(e)))
            log("Reintentando: %s" % errores[-1])
    # perfil danado -> uno nuevo
    try:
        shutil.rmtree(nuevo, ignore_errors=True)
        os.makedirs(nuevo, exist_ok=True)
        log("Probando con un perfil nuevo (tendra que iniciar sesion otra vez).")
        d = webdriver.Chrome(options=_opciones(webdriver.ChromeOptions, nuevo, ancho, True, extra, headless))
        return d
    except Exception as e:
        errores.append("Chrome perfil nuevo: %s" % _msg(e))
        shutil.rmtree(nuevo, ignore_errors=True)      # no dejar un perfil vacio como activo
    # Edge
    try:
        log("Probando con Microsoft Edge.")
        pe = perfil + "_edge"
        os.makedirs(pe, exist_ok=True)
        return webdriver.Edge(options=_opciones(webdriver.EdgeOptions, pe, ancho, True, extra, headless))
    except Exception as e:
        errores.append("Edge: %s" % _msg(e))
    raise SystemExit("No se pudo abrir ningun navegador.\n" + "\n".join(errores) +
                     "\n\nRevise: 1) que Chrome este instalado y actualizado, 2) pip install -U selenium, "
                     "3) que el antivirus no bloquee chromedriver.")
