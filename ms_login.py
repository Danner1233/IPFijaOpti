# -*- coding: utf-8 -*-
"""Inicio de sesion de Microsoft (SharePoint / Outlook) para los lectores.

Hace lo que se puede automatizar: escribe el usuario y la clave (si estan en Ajustes), acepta "Mantener sesion"
y, cuando Microsoft pide el NUMERO de verificacion, lo lee de la pantalla y lo muestra en una ventanita grande
(siempre visible) para que lo apruebe en su celular. Con la sesion guardada en el perfil no se vuelve a pedir.
La aprobacion en el celular siempre la hace la persona.
"""
import json
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from hac_zac import log as _log  # noqa: E402
from hac_zac.rutas import data_dir  # noqa: E402

_LOG = _log.obtener("ms_login")

# Mira la pagina actual y dice en que paso de Microsoft esta. No cambia nada.
JS_FASE = """
const v = e => !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const q = s => document.querySelector(s);
const host = location.hostname.toLowerCase();
if (!/login\\.(microsoftonline|live)\\.com|microsoft\\.com$/.test(host)) return {fase: 'otro', host: host};
const num = q('#idRichContext_DisplaySign, [data-testid="displaySign"], .displaySign');
if (num && v(num) && /\\d/.test(num.innerText)) return {fase: 'numero', numero: (num.innerText.match(/\\d+/)||[''])[0]};
if (v(q('#i0118')) ) return {fase: 'clave'};
if (v(q('#i0116')) ) return {fase: 'correo'};
if (v(q('#KmsiCheckboxField')) || /Stay signed in|Mantener la sesi/i.test(document.body.innerText)) return {fase: 'mantener'};
return {fase: 'espera'};
"""
JS_ESCRIBIR = """
const e = document.querySelector(arguments[0]); if (!e) return false;
e.focus(); e.value = arguments[1];
e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
return true;
"""
JS_SIGUIENTE = """
const b = document.querySelector('#idSIButton9'); if (!b) return false; b.click(); return true;
"""
JS_MANTENER = """
const c = document.querySelector('#KmsiCheckboxField'); if (c && !c.checked) c.click();
const b = document.querySelector('#idSIButton9'); if (b) b.click(); return true;
"""


def _archivo_numero():
    return data_dir() / "auth_numero.json"


def mostrar_numero(numero):
    """Escribe el numero y abre una ventana pequena, arriba de todo, que se cierra sola al aprobar."""
    try:
        _archivo_numero().write_text(json.dumps({"numero": numero, "hora": time.time()}), encoding="utf-8")
        subprocess.Popen([sys.executable, os.path.join(AQUI, "ms_numero.py"), str(_archivo_numero())],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        _LOG.exception("no se pudo mostrar el numero")


def ocultar_numero():
    try:
        _archivo_numero().unlink()
    except OSError:
        pass


def asegurar_sesion(driver, es_destino, usuario="", clave="", espera_max=300, log=print, pausa=1.5, mostrar=None):
    """Devuelve True cuando la pagina ya esta en el destino (es_destino(url) verdadero).
    Si pasan `espera_max` segundos sin lograrlo, devuelve False."""
    limite = time.time() + espera_max
    numero_mostrado = None
    intentos = {"correo": 0, "clave": 0}
    while time.time() < limite:
        try:
            if es_destino(driver.current_url):
                if numero_mostrado:
                    ocultar_numero()
                return True
            f = driver.execute_script(JS_FASE) or {}
        except Exception:
            _LOG.exception("no pude leer la pagina de inicio de sesion")
            time.sleep(pausa)
            continue
        fase = f.get("fase")
        if fase == "numero":
            if f.get("numero") != numero_mostrado:
                numero_mostrado = f.get("numero")
                log("Microsoft pide verificacion: apruebe en su celular el numero %s" % numero_mostrado)
                mostrar_numero(numero_mostrado)
        elif fase == "correo" and usuario and intentos["correo"] < 3:
            intentos["correo"] += 1
            driver.execute_script(JS_ESCRIBIR, "#i0116", usuario)
            driver.execute_script(JS_SIGUIENTE)
        elif fase == "clave" and clave and intentos["clave"] < 3:
            intentos["clave"] += 1
            driver.execute_script(JS_ESCRIBIR, "#i0118", clave)
            driver.execute_script(JS_SIGUIENTE)
        elif fase == "mantener":
            driver.execute_script(JS_MANTENER)
        elif fase in ("correo", "clave"):
            log("Falta %s en Ajustes (o ya fallo 3 veces): escribalo en la ventana de Chrome." %
                ("el usuario" if fase == "correo" else "la clave"))
            if mostrar:                      # si estaba oculta, hay que verla para escribir
                try:
                    mostrar()
                except Exception:
                    pass
            intentos[fase] += 1 if intentos[fase] >= 3 else 0
        time.sleep(pausa)
    if numero_mostrado:
        ocultar_numero()
    return False
