# -*- coding: utf-8 -*-
"""
portal_csr.py  -  Consulta del Support Portal (CSR) con Selenium.

Se puede usar de 3 formas:

1) Como modulo / CLI (lo usa SCRIPT_HAC_ZAC_IP_C2_MANUAL.py desde SecureCRT):
       python portal_csr.py --modo serial --valor ZTEGDD1ACC08 --json
       python portal_csr.py --modo mac    --valor 68:2a:dd:98:fe:3b --json

2) Como aplicacion con ventana (sin argumentos):
       python portal_csr.py

3) Depuracion (guarda el HTML del formulario de busqueda):
       python portal_csr.py --modo serial --valor X --debug

Credenciales: variables de entorno PORTAL_USER / PORTAL_PASS
(o constantes de abajo). Requiere:  pip install selenium
"""

import argparse
import json
import os
import re
import sys
import time

from selenium import webdriver
from selenium.common.exceptions import (
    NoAlertPresentException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL_LOGIN = "https://acstr069.claro.net.co/CSR/Login.aspx"
PORTAL_USER = os.environ.get("PORTAL_USER", "")
PORTAL_PASS = os.environ.get("PORTAL_PASS", "")
NAVEGADOR = os.environ.get("PORTAL_BROWSER", "chrome")   # chrome | edge
HEADLESS = os.environ.get("PORTAL_HEADLESS", "0") == "1"  # por defecto el navegador se VE
TIMEOUT = 25

ETIQUETAS = {
    "serial": ["serial number", "serial"],
    "mac": ["mac address", "mac"],
}

CARPETA = os.path.dirname(os.path.abspath(__file__))


class PortalError(Exception):
    pass


# ------------------------------------------------------------------
# Navegador
# ------------------------------------------------------------------
def crear_driver(headless=HEADLESS, navegador=NAVEGADOR):
    """Chrome visible con un perfil propio fuera de TEMP/OneDrive (evita 'cannot create temp dir for user data
    dir'). Si Chrome falla, navegador.py reintenta (modo compatible, perfil nuevo, Edge)."""
    if CARPETA not in sys.path:
        sys.path.insert(0, CARPETA)
    from navegador import abrir_navegador
    perfil = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "perfil_portal")
    return abrir_navegador(perfil, "1400,1000", log=lambda m: print(m, file=sys.stderr, flush=True),
                           extra=("--ignore-certificate-errors", "--log-level=3"), headless=headless, proceso="portal")


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------
def _visible(el):
    try:
        return el.is_displayed() and el.is_enabled()
    except WebDriverException:
        return False


def _click_ok_visibles(d, ids=("btnAlertOk_btn", "btnOk_btn"), espera=3):
    """Pulsa OK en cualquier confirmacion (popup de la pagina o alert JS)."""
    fin = time.time() + espera
    clics = 0
    while time.time() < fin:
        hecho = False
        try:
            d.switch_to.alert.accept()
            hecho = True
        except NoAlertPresentException:
            pass
        for i in ids:
            try:
                b = d.find_element(By.ID, i)
                if _visible(b):
                    b.click()
                    hecho = True
            except (NoSuchElementException, WebDriverException):
                pass
        if hecho:
            clics += 1
            time.sleep(0.6)
        else:
            time.sleep(0.3)
    return clics


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------
def login(d, usuario, clave):
    d.get(URL_LOGIN)
    w = WebDriverWait(d, TIMEOUT)
    w.until(EC.visibility_of_element_located((By.ID, "txtName"))).send_keys(usuario)
    d.find_element(By.ID, "txtPassword").send_keys(clave)
    d.find_element(By.ID, "btnLogin_btn").click()

    # Confirmaciones "a veces" -> siempre OK
    _click_ok_visibles(d, espera=3)

    try:
        w.until(lambda x: "Default.aspx" in x.current_url
                or x.find_elements(By.ID, "frmDesktop"))
    except TimeoutException:
        msg = ""
        try:
            msg = d.find_element(By.ID, "lblNotCorrect").text
        except NoSuchElementException:
            pass
        raise PortalError("No se pudo iniciar sesion. %s" % msg)

    _click_ok_visibles(d, espera=2)


# ------------------------------------------------------------------
# Busqueda (formulario dentro del iframe frmDesktop)
# ------------------------------------------------------------------
def _entrar_frame_busqueda(d):
    d.switch_to.default_content()
    WebDriverWait(d, TIMEOUT).until(
        EC.frame_to_be_available_and_switch_to_it((By.ID, "frmDesktop"))
    )


def _xpath_texto(texto):
    t = texto.lower()
    tr = "translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
    return "//*[self::label or self::span or self::a or self::td or self::div or self::option or self::li][%s='%s' or %s='%s:']" % (tr, t, tr, t)


def _seleccionar_modo(d, modo):
    """Elige Serial Number o MAC Address. Devuelve el input asociado si lo hay."""
    for etiqueta in ETIQUETAS[modo]:
        # 1) <select> con esa opcion
        for sel in d.find_elements(By.TAG_NAME, "select"):
            if not _visible(sel):
                continue
            for op in sel.find_elements(By.TAG_NAME, "option"):
                if op.text.strip().lower().rstrip(":") == etiqueta:
                    op.click()
                    return None
        # 2) label/radio/enlace con ese texto
        for el in d.find_elements(By.XPATH, _xpath_texto(etiqueta)):
            if not _visible(el):
                continue
            destino = el.get_attribute("for")
            try:
                el.click()
            except WebDriverException:
                continue
            if destino:
                try:
                    return d.find_element(By.ID, destino)
                except NoSuchElementException:
                    pass
            return None
    return None


def _campo_texto(d):
    for inp in d.find_elements(By.CSS_SELECTOR, "input[type=text], input:not([type])"):
        if _visible(inp):
            return inp
    return None


def _boton_buscar(d):
    xp = ("//input[(@type='button' or @type='submit') and "
          "contains(translate(@value,'SEARCH','search'),'search')]"
          " | //button[contains(translate(.,'SEARCH','search'),'search')]")
    for b in d.find_elements(By.XPATH, xp):
        if _visible(b):
            return b
    return None


def buscar(d, modo, valor, debug=False):
    modo = modo.lower()
    if modo not in ETIQUETAS:
        raise PortalError("Modo invalido: %s (use serial o mac)" % modo)

    _entrar_frame_busqueda(d)
    time.sleep(1.5)

    if debug:
        ruta = os.path.join(CARPETA, "portal_debug_busqueda.html")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(d.page_source)

    asociado = _seleccionar_modo(d, modo)
    time.sleep(0.5)

    campo = asociado if (asociado is not None and _visible(asociado)) else _campo_texto(d)
    if campo is None:
        raise PortalError(
            "No encontre el campo de busqueda. Ejecute con --debug y revise "
            "portal_debug_busqueda.html"
        )
    campo.clear()
    campo.send_keys(valor.strip())

    boton = _boton_buscar(d)
    if boton is not None:
        boton.click()
    else:
        campo.send_keys(Keys.ENTER)

    d.switch_to.default_content()


# ------------------------------------------------------------------
# Lectura de Subscriber info / Device information
# ------------------------------------------------------------------
JS_LEER = """
var out = {};
document.querySelectorAll('span.left_information_name').forEach(function(n){
  var v = n.parentNode.querySelector('span.left_information_value');
  if (v) { out[n.textContent.replace(/:\\s*$/, '').trim()] = v.textContent.trim(); }
});
return out;
"""


def leer_info(d):
    d.switch_to.default_content()
    try:
        WebDriverWait(d, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "rptDeviceInfo_ctl00_lblValue"))
        )
    except TimeoutException:
        _click_ok_visibles(d, espera=2)   # posible mensaje "no encontrado"
        raise PortalError("El portal no devolvio el dispositivo (no existe o no cargo).")

    time.sleep(0.8)
    return d.execute_script(JS_LEER)


def _megas(info):
    """Megas si el portal las muestra en algun campo (speed/plan/profile/megas...)."""
    for k, v in info.items():
        if re.search(r"speed|bandwidth|profile|plan|mega|veloc", k, re.I):
            m = re.search(r"(\d+)", v or "")
            if m:
                return m.group(1)
    return ""


def normalizar(info):
    """Campos que usa el script de SecureCRT."""
    g = lambda k: info.get(k, "").strip()
    return {
        "cliente": g("User name"),
        "ubicacion": g("User location"),
        "mycust03": g("mycust03"),
        "cuenta_rr": g("mycust04"),
        "serial": g("Serial number"),
        "fabricante": g("Manufacturer"),
        "oui": g("Manufacturer OUI"),
        "product_class": g("Product class"),
        "hardware": g("Hardware version"),
        "firmware": g("Firmware version"),
        "ip": g("IP address"),
        "mac": g("Mac address"),
        "megas": _megas(info),
        "crudo": info,
    }


def consultar(modo, valor, usuario=None, clave=None, headless=HEADLESS, debug=False):
    usuario = usuario or PORTAL_USER
    clave = clave or PORTAL_PASS
    if not usuario or not clave:
        raise PortalError("Faltan PORTAL_USER / PORTAL_PASS.")

    d = crear_driver(headless=headless)
    try:
        login(d, usuario, clave)
        buscar(d, modo, valor, debug=debug)
        info = leer_info(d)
        if debug:
            # Guarda la pantalla del dispositivo para ubicar dónde están las megas
            try:
                d.switch_to.frame("frmDesktop")
                ruta = os.path.join(CARPETA, "portal_debug_dispositivo.html")
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(d.page_source)
                d.switch_to.default_content()
            except Exception:
                pass
        return normalizar(info)
    finally:
        try:
            d.quit()
        except Exception:
            pass


# ------------------------------------------------------------------
# CLI / App
# ------------------------------------------------------------------
def _app():
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Consulta Support Portal")
    modo = tk.StringVar(value="serial")
    valor = tk.StringVar()
    salida = tk.Text(root, width=60, height=14)

    def ir():
        salida.delete("1.0", "end")
        try:
            r = consultar(modo.get(), valor.get())
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        for k in ("cliente", "ubicacion", "mycust03", "cuenta_rr", "serial",
                  "fabricante", "oui", "product_class", "hardware",
                  "firmware", "ip", "mac"):
            salida.insert("end", "%s: %s\n" % (k, r[k]))

    tk.Radiobutton(root, text="Serial Number", variable=modo, value="serial").pack(anchor="w")
    tk.Radiobutton(root, text="MAC Address", variable=modo, value="mac").pack(anchor="w")
    tk.Entry(root, textvariable=valor, width=40).pack(padx=8, pady=4)
    tk.Button(root, text="Consultar", command=ir).pack(pady=4)
    salida.pack(padx=8, pady=8)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["serial", "mac"])
    ap.add_argument("--valor")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--ver", action="store_true", help="mostrar el navegador")
    a = ap.parse_args()

    if not a.modo or not a.valor:
        _app()
        return 0

    try:
        r = consultar(a.modo, a.valor, headless=HEADLESS, debug=a.debug)
        r["ok"] = True
    except Exception as e:
        r = {"ok": False, "error": str(e)}

    if a.json:
        print(json.dumps(r, ensure_ascii=True))
    else:
        for k, v in r.items():
            if k != "crudo":
                print("%s: %s" % (k, v))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
