"""Diligenciamiento de Microsoft Forms con Playwright (Edge). Portado de runform() del script original.

Se importa 'playwright' solo al ejecutar, así la app abre aunque no esté instalado.
Requiere:  pip install playwright   (usa el Edge ya instalado; no hace falta 'playwright install').
"""
from __future__ import annotations

import os
import re
from typing import Callable, Optional

from .documentacion import cargar_config, marcar_documentada
from .rutas import data_dir


class FormsError(Exception):
    pass


def _temp_propio() -> str:
    """Playwright crea carpetas temporales (playwright-artifacts-XXXXXX). Si TEMP apunta a una carpeta que no
    existe (p. ej. SecureCRT Portable\\Data\\Temp) falla con ENOENT: se usa una carpeta propia que siempre existe."""
    base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "tmp")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return os.environ.get("TEMP", "")
    os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = base
    return base


# Basura que no hace falta copiar (se regenera) y candados que impedirian abrir el perfil copiado.
_NO_COPIAR = ("Cache", "Code Cache", "GPUCache", "GrShaderCache", "GraphiteDawnCache", "ShaderCache", "DawnCache",
              "Crashpad", "BrowserMetrics*", "CrashpadMetrics*", "Singleton*", "lockfile", "LOCK")


def perfil_forms() -> str:
    """Perfil del navegador de Forms FUERA de OneDrive (OneDrive bloquea/sincroniza los archivos del perfil y el
    navegador falla al arrancar), junto a los demas perfiles en %LOCALAPPDATA%\\hac_zac\\.
    La primera vez copia el perfil viejo (carpeta de datos\\browser_profile) para conservar la sesion iniciada;
    el viejo queda intacto y se puede borrar a mano cuando todo funcione."""
    import shutil
    nuevo = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "perfil_forms")
    viejo = str(data_dir() / "browser_profile")
    if not os.path.isdir(nuevo) and os.path.isdir(viejo):
        try:
            shutil.copytree(viejo, nuevo, ignore=shutil.ignore_patterns(*_NO_COPIAR))
        except Exception:
            shutil.rmtree(nuevo, ignore_errors=True)     # copia a medias: mejor perfil limpio (pide iniciar sesion)
    os.makedirs(nuevo, exist_ok=True)
    return nuevo


def _fill(page, q, val, timeout=15000):
    # .count() no espera; wait_for() sí (Forms renderiza por JS y tarda unos segundos).
    loc = page.get_by_text(q, exact=True)
    try:
        loc.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        loc = page.get_by_text(re.compile(re.escape(q), re.I))
        try:
            loc.first.wait_for(state="visible", timeout=timeout)
        except Exception:
            raise FormsError("No encontré la pregunta: " + q)
    p = loc.last.locator("xpath=..")
    for _ in range(6):
        for css in ("input", "textarea"):
            x = p.locator(css).first
            try:
                if x.count() and x.is_visible():
                    x.fill(str(val or ""))
                    return
            except Exception:
                pass
        p = p.locator("xpath=..")
    raise FormsError("No pude ubicar el campo: " + q)


def _opt(page, s, timeout=15000):
    for role in ("radio", "option"):
        x = page.get_by_role(role, name=s, exact=True)
        try:
            x.first.wait_for(state="visible", timeout=3000)
            x.first.click()
            return
        except Exception:
            pass
    x = page.get_by_text(s, exact=True)
    try:
        x.first.wait_for(state="visible", timeout=timeout)
        x.last.click()
        return
    except Exception:
        pass
    raise FormsError("No pude seleccionar: " + s)


def ejecutar_formulario(d: dict, confirmar_envio: Callable[[], bool], log: Callable[[str], None] = lambda t: None,
                        tras_envio: Optional[Callable[[], None]] = None) -> str:
    """Devuelve 'enviado' o 'cancelado'. Lanza FormsError ante cualquier problema (no declara éxito a medias)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FormsError("Falta instalar Playwright:  pip install playwright")
    cfg = cargar_config()
    _temp_propio()                      # antes de iniciar Playwright: el proceso hijo hereda TEMP
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            perfil_forms(), channel=cfg.get("browser_channel", "msedge"),
            headless=False, args=["--test-type"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log("Abriendo el formulario…")
            page.goto(cfg["form_url"], wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(800)

            log("Página 1: ID del caso, cuenta RR, regional y resultado…")
            _fill(page, "ID CASO", d["id"])
            _fill(page, "Cuenta_RR", d["rr"])
            _opt(page, cfg["regional"].get(d["regional"], d["regional"]))
            _opt(page, cfg["success_option"])
            page.get_by_role("button", name=re.compile("Siguiente", re.I)).last.click()
            page.wait_for_timeout(800)

            log("Página 2: actividad, red y direccionamiento…")
            _opt(page, d["actividad"])
            _opt(page, cfg["property_network"].get(d["propiedad"].upper(), d["propiedad"]))
            for q, v in [("OLT ATP.", d["olt"]), ("IP Asignada", d["ip"]), ("Puerta Enlace", d["gw"]),
                         ("MASCARA_IP.", d["mask"]), ("IP Bridge Asignada", d["bridge_ip"] or "0"),
                         ("IP DMZ", d["dmz"] or "0"), ("IP Forwarding", d["forward"] or "0"),
                         ("Pto Port Forwarding", d["port"] or "0")]:
                _fill(page, q, v)
            log("Formulario diligenciado. Revíselo en el navegador.")

            if not confirmar_envio():
                log("Envío cancelado por el usuario (el formulario no se envió).")
                return "cancelado"

            btn = page.get_by_role("button", name=re.compile(r"^Enviar$", re.I))
            if not btn.count():
                btn = page.get_by_text(re.compile(r"^Enviar$", re.I))
            if not btn.count():
                raise FormsError("No encontré el botón 'Enviar' en Microsoft Forms.")
            btn.last.click()
            page.wait_for_timeout(1200)
            marcar_documentada(d)        # solo después de que Forms aceptó el envío
            log("Microsoft Forms recibió el envío. Cuenta registrada como DOCUMENTADA.")
            if tras_envio:
                tras_envio()             # alerta «Documentación enviada»; al aceptar se cierra la pantalla (finally)
            return "enviado"
        finally:
            try:
                ctx.close()
            except Exception:
                pass
