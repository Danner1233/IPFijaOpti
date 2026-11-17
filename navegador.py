# -*- coding: utf-8 -*-
"""Abre Chrome (visible, con la sesion guardada) de forma robusta para los lectores.

Si Chrome "se cae" al arrancar:
  1) cierra procesos que quedaron colgados con ESTE perfil (no toca su Chrome normal) y borra bloqueos;
  2) reintenta con opciones de compatibilidad;
  3) si el perfil esta danado, usa uno nuevo (habra que iniciar sesion otra vez);
  4) como ultimo recurso abre Microsoft Edge (viene con Windows).
El navegador SIEMPRE se muestra: no se oculta.
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
    cambio se nota en segundos. `forzar=True` la muestra (p. ej. si hace falta escribir algo en ella)."""
    ver = ver_navegador(proceso) if forzar is None else bool(forzar)
    if getattr(driver, "_hz_ver", None) == ver:
        return
    try:
        x, y = DENTRO if ver else FUERA
        driver.set_window_position(x, y)
        driver._hz_ver = ver
    except Exception:
        pass


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
