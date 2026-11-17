# -*- coding: utf-8 -*-
"""Busca en Outlook web / Outlook nuevo, con SU sesion del navegador, SOLO el correo de las solicitudes que ya se
asigno en SharePoint (por cuenta RR) y guarda la plantilla completa en la cola. No abre los demas correos.

Primera vez:  python correo_lector.py --ver        (inicie sesion en Outlook en la ventana y pulse Enter)
Despues:      python correo_lector.py              (busca cada minuto la cuenta RR de sus solicitudes, en segundo plano)
Diagnostico:  python correo_lector.py --una --debug   (guarda outlook_debug_lista.html y outlook_debug_mensaje.txt;
              si no encuentra el buscador, filas o texto: outlook_debug_diagnostico.txt, _pagina.html, _pantalla.png)
Prueba:       python correo_lector.py --archivo correo.txt    (sin navegador)

Requiere: pip install selenium
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from hac_zac import cola
from hac_zac import log as _log

_LOG = _log.obtener('correo_lector')  # noqa: E402

URL = "https://outlook.office.com/mail/inbox"
# Fuera de OneDrive: OneDrive sincroniza/bloquea la carpeta de sesion de Chrome y Chrome no arranca.
PERFIL = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "perfil_correo")
CLAVE_ASUNTO = "solicitud de ip fija"          # el correo se reconoce por esta frase (asunto o vista previa)
VISTOS = os.path.join(AQUI, "correos_vistos.txt")


def abrir(ver=True):
    """Se ve u oculta segun Ajustes > Ver navegador (por defecto se ve)."""
    from navegador import abrir_navegador
    d = abrir_navegador(PERFIL, "1400,900", log=lambda m: print(m, flush=True), proceso="correo")
    d.get(URL)
    return d


def _vistos():
    try:
        with open(VISTOS, encoding="utf-8") as f:
            return set(x.strip() for x in f if x.strip())
    except Exception:
        return set()


def _marcar(clave):
    with open(VISTOS, "a", encoding="utf-8") as f:
        f.write(clave + "\n")


def hora_de(etiqueta):
    """Intenta sacar la hora del texto del correo ('12/11/2026 10:04'); si no, None."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\D{1,10}(\d{1,2}):(\d{2})", etiqueta or "")
    if not m:
        return None
    dd, mm, aa, hh, mi = (int(x) for x in m.groups())
    aa += 2000 if aa < 100 else 0
    try:
        return datetime(aa, mm, dd, hh, mi).isoformat(timespec="seconds")
    except ValueError:
        return None


CADA_S = 60            # el correo se actualiza y se busca cada 1 minuto
MAX_RESULTADOS = 8     # correos que se abren por busqueda (los mas recientes de esa cuenta RR)

ESPERA_LISTA_S = 12    # maximo que se espera a que Outlook muestre los resultados de la busqueda
ESPERA_LECTURA_S = 8   # maximo que se espera a que cargue el panel de lectura al abrir un correo

# Se prueban en orden; el primero visible gana. Outlook web cambia el HTML a menudo: por eso hay varios.
CAJAS_BUSQUEDA = ('#topSearchInput', 'input#searchBoxInput', '#searchBoxId input',
                  'input[aria-label*="Buscar" i]', 'input[aria-label*="Search" i]',
                  'input[placeholder*="Buscar" i]', 'input[placeholder*="Search" i]',
                  '[role="search"] input', 'input[type="search"]')
# Filas de la lista de correos. El ultimo (generico) puede tocar las sugerencias del buscador: va al final.
SEL_RESULTADOS = ('[role="listbox"] [role="option"][data-convid]',
                  '[role="option"][data-convid]',
                  'div[data-convid][data-focusable-row]',
                  '[aria-label*="Lista de mensajes" i] [role="option"]',
                  '[aria-label*="Message list" i] [role="option"]',
                  '[role="main"] [role="listbox"] [role="option"]')
# Devuelve el texto de CADA mensaje del panel de lectura (una conversacion puede traer varios).
JS_LECTURA = """
var sels = ['[aria-label="Cuerpo del mensaje"]', '[aria-label="Message body"]', '[role="document"]',
            '#ReadingPaneContainerId'];
for (var i = 0; i < sels.length; i++) {
  var es = document.querySelectorAll(sels[i]), out = [];
  for (var j = 0; j < es.length; j++) { var t = (es[j].innerText || '').trim(); if (t) out.push(t); }
  if (out.length) return out;
}
return [];
"""


def id_del_correo(texto):
    """SOLICITUD ID que trae el cuerpo del correo ('' si no es una solicitud)."""
    from hac_zac import plantilla
    return plantilla.parsear_solicitud(texto or "").get("solicitud_id", "")


def elegir_correo(sol_id, n, leer, log=print):
    """Abre hasta `n` correos (leer(i) -> (texto, hora)) y devuelve (texto, hora) del que trae EXACTAMENTE la
    SOLICITUD ID `sol_id`. Los que traen otro ID (otra solicitud de la misma cuenta) se ignoran."""
    otros = []
    for i in range(n):
        texto, hora = leer(i)
        if not texto:
            continue
        id_ = id_del_correo(texto)
        if not id_:
            continue
        if id_ == str(sol_id):
            return texto, hora
        otros.append(id_)
    if otros:
        log("   correos de esa cuenta con otro ID (%s): ninguno es la solicitud %s" % (", ".join(otros), sol_id))
    return None


def elegir_texto(textos, sol_id):
    """De los mensajes del panel de lectura, el que trae la SOLICITUD ID `sol_id`; si ninguno, el primero que
    sea una solicitud; si tampoco, el primero ('' si no hay)."""
    if isinstance(textos, str):
        textos = [textos]
    textos = [t for t in (textos or []) if t]
    ids = [id_del_correo(t) for t in textos]
    for t, i in zip(textos, ids):
        if i and i == str(sol_id):
            return t
    for t, i in zip(textos, ids):
        if i:
            return t
    return textos[0] if textos else ""


def esperar(condicion, maximo, paso=0.5, dormir=time.sleep):
    """Repite condicion() hasta que devuelva algo verdadero o pasen `maximo` segundos. Devuelve el ultimo valor."""
    v = condicion()
    t = 0.0
    while not v and t < maximo:
        dormir(paso)
        t += paso
        v = condicion()
    return v


def _visible(e):
    try:
        return e.is_displayed()
    except Exception:
        return False


def _caja_busqueda(driver):
    from selenium.webdriver.common.by import By
    for css in CAJAS_BUSQUEDA:
        for e in driver.find_elements(By.CSS_SELECTOR, css):
            if _visible(e):
                return e
    return None


def _resultados(driver):
    """Filas de correos con el primer selector de SEL_RESULTADOS que encuentre alguna."""
    from selenium.webdriver.common.by import By
    for css in SEL_RESULTADOS:
        try:
            es = driver.find_elements(By.CSS_SELECTOR, css)
        except Exception:
            continue
        if es:
            return es
    return []


def _firma(driver):
    """Identifica la lista que se ve (para saber cuando Outlook ya cambio a los resultados nuevos)."""
    try:
        es = _resultados(driver)
        if not es:
            return ""
        e = es[0]
        return (e.get_attribute("data-convid") or "") + "|" + (e.get_attribute("aria-label") or e.text or "")[:120]
    except Exception:
        return ""


def _buscar_rr(driver, rr):
    """Escribe la cuenta RR (solo digitos, sin puntos) en el buscador de Outlook, la ejecuta y espera a que la
    lista cambie (si no, se leerian los resultados de la busqueda anterior)."""
    from selenium.webdriver.common.keys import Keys
    caja = esperar(lambda: _caja_busqueda(driver), 6)
    if caja is None:
        raise RuntimeError("No encuentro el buscador de Outlook (abra la bandeja de entrada en la ventana).")
    antes = _firma(driver)
    caja.click()
    caja.send_keys(Keys.CONTROL, "a")
    caja.send_keys(Keys.DELETE)
    caja.send_keys(rr)
    caja.send_keys(Keys.ENTER)
    time.sleep(1.5)
    esperar(lambda: _resultados(driver) and _firma(driver) != antes, ESPERA_LISTA_S)
    time.sleep(0.8)                                     # deja terminar de pintar la lista


def _leer_panel(driver, antes=""):
    """Textos del panel de lectura cuando ya cargo un mensaje distinto al anterior."""
    def listo():
        try:
            ts = driver.execute_script(JS_LECTURA) or []
        except Exception:
            return None
        if isinstance(ts, str):
            ts = [ts]
        return ts if ts and "\n".join(ts) != antes else None
    return esperar(listo, ESPERA_LECTURA_S) or []


def _releer(driver, textos, sol_id, espera=2.0, dormir=time.sleep):
    """Segunda lectura del panel cuando la primera no trajo SOLICITUD ID. Devuelve (texto, textos)."""
    dormir(espera)
    try:
        nuevos = driver.execute_script(JS_LECTURA) or []
    except Exception:
        nuevos = []
    if isinstance(nuevos, str):
        nuevos = [nuevos]
    if nuevos and any(id_del_correo(t) for t in nuevos):
        return elegir_texto(nuevos, sol_id), nuevos
    return elegir_texto(textos, sol_id), textos


def _volcar_diagnostico(driver, motivo):
    """--debug: guarda lo necesario para ajustar selectores cuando algo NO se encuentra.
    Ojo: outlook_debug_pagina.html y la captura pueden traer datos de clientes; no los publique."""
    from selenium.webdriver.common.by import By
    lineas = ["motivo: " + motivo, "fecha: " + datetime.now().isoformat(timespec="seconds")]
    try:
        lineas += ["url: " + driver.current_url, "titulo: " + driver.title]
    except Exception:
        pass
    for nombre, sels in (("buscador", CAJAS_BUSQUEDA), ("resultados", SEL_RESULTADOS)):
        lineas.append("")
        lineas.append("== %s ==" % nombre)
        for css in sels:
            try:
                es = driver.find_elements(By.CSS_SELECTOR, css)
                lineas.append("%-55s %d (visibles %d)" % (css, len(es), sum(1 for e in es if _visible(e))))
            except Exception as e:
                lineas.append("%-55s error %s" % (css, e))
    lineas += ["", "== inputs visibles (id | aria-label | placeholder) =="]
    try:
        for e in driver.find_elements(By.CSS_SELECTOR, "input"):
            if _visible(e):
                lineas.append(" | ".join(e.get_attribute(a) or "" for a in ("id", "aria-label", "placeholder")))
    except Exception:
        pass
    lineas += ["", "== roles listbox/option =="]
    try:
        for css in ('[role="listbox"]', '[role="option"]', '[data-convid]', '[role="document"]'):
            lineas.append("%-20s %d" % (css, len(driver.find_elements(By.CSS_SELECTOR, css))))
    except Exception:
        pass
    with open(os.path.join(AQUI, "outlook_debug_diagnostico.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    try:
        with open(os.path.join(AQUI, "outlook_debug_pagina.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot(os.path.join(AQUI, "outlook_debug_pantalla.png"))
    except Exception:
        pass
    print("   [debug] guardado outlook_debug_diagnostico.txt (+ pagina.html y pantalla.png): " + motivo)


def _guardar_en_mi_cola(texto, hora, sol):
    r = cola.registrar_correo(texto, recibido=hora)
    return r[0] if r else None


def revisar(driver, debug=False, pendientes=None, guardar=None):
    """Por cada solicitud sin plantilla: busca su cuenta RR en Outlook, abre los correos que salen,
    confirma que el SOLICITUD ID sea el de la solicitud y recien ahi guarda la plantilla.
    pendientes: {RR: {"id": ...}} (por defecto, mis solicitudes de la cola sin plantilla).
    guardar(texto, hora, sol) -> id guardado o None (por defecto, en mi cola). El servidor central pasa los suyos."""
    if pendientes is None:
        pendientes = cola.pendientes_correo()      # {RR: mi solicitud sin plantilla}
    guardar = guardar or _guardar_en_mi_cola
    if not pendientes:
        return 0
    nuevos = 0
    for rr, sol in list(pendientes.items()):
        rr = cola.solo_digitos(rr)
        if not rr:
            continue
        try:
            _buscar_rr(driver, rr)
        except Exception as e:
            print("   no pude buscar la cuenta %s: %s" % (rr, e))
            _LOG.warning("busqueda RR %s: %s", rr, e)
            if debug:
                _volcar_diagnostico(driver, "no se encontro el buscador (cuenta %s)" % rr)
            continue
        n = min(len(_resultados(driver)), MAX_RESULTADOS)
        if debug and n:
            with open(os.path.join(AQUI, "outlook_debug_lista.html"), "w", encoding="utf-8") as f:
                f.write("\n\n".join(i.get_attribute("outerHTML") for i in _resultados(driver)[:5]))
        if not n:
            print("   cuenta %s: Outlook no muestra correos todavia" % rr)
            _LOG.info("cuenta %s (solicitud %s): la busqueda no dio correos", rr, sol["id"])
            if debug:
                _volcar_diagnostico(driver, "la busqueda de la cuenta %s no dio filas" % rr)
            continue
        previo = {"texto": ""}

        def leer(i, rr=rr, sol_id=sol["id"]):
            try:
                it = _resultados(driver)[i]
                etiqueta = it.get_attribute("aria-label") or it.text or ""
                it.click()
                textos = _leer_panel(driver, previo["texto"])
                previo["texto"] = "\n".join(textos)
                texto = elegir_texto(textos, sol_id)
                if textos and not id_del_correo(texto):
                    # El panel pudo leerse antes de terminar de cargar el cuerpo: se espera y se lee otra vez.
                    texto, textos = _releer(driver, textos, sol_id)
                if debug:
                    with open(os.path.join(AQUI, "outlook_debug_mensaje.txt"), "w", encoding="utf-8") as f:
                        f.write(etiqueta + "\n\n" + ("\n\n----- mensaje -----\n\n".join(textos) or "(panel vacio)"))
                    if not textos:
                        _volcar_diagnostico(driver, "el panel de lectura no mostro texto (cuenta %s)" % rr)
                return texto, hora_de(etiqueta)
            except Exception as e:
                _LOG.warning("no pude abrir el resultado %s de la cuenta %s: %s", i, rr, e)
                return "", None

        hallado = elegir_correo(sol["id"], n, leer, log=lambda m: (print(m), _LOG.info(m.strip())))
        if not hallado:
            print("   cuenta %s: aun no llega el correo de la solicitud %s" % (rr, sol["id"]))
            _LOG.info("cuenta %s (solicitud %s): %d correo(s) abiertos, ninguno con ese SOLICITUD ID", rr, sol["id"], n)
            continue
        texto, hora = hallado
        r = guardar(texto, hora, sol)
        if r:
            nuevos += 1
            print("   plantilla guardada para la solicitud", r, "- lista para el script")
            _LOG.info("cuenta %s: plantilla guardada para la solicitud %s", rr, r)
    return nuevos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true")
    ap.add_argument("--una", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--archivo", help="texto de un correo guardado (prueba sin navegador)")
    ap.add_argument("--cada", type=int, default=CADA_S, help="segundos entre revisiones (60 = cada minuto)")
    a = ap.parse_args()

    if a.archivo:
        with open(a.archivo, encoding="utf-8") as f:
            print(cola.registrar_correo(f.read()))
        return

    d = abrir(a.ver)
    import ms_login
    from hac_zac import credenciales
    cr = credenciales.cargar()
    en_outlook = lambda u: "outlook." in u.split("/")[2].lower() if "//" in u else False
    from navegador import aplicar_visibilidad
    if not ms_login.asegurar_sesion(d, en_outlook, cr.get("ms_usuario", ""), cr.get("ms_clave", ""),
                                    mostrar=lambda: aplicar_visibilidad(d, "correo", True)):
        print("No se pudo iniciar sesion en Outlook en 5 minutos; escribalo en la ventana de Chrome.")
    try:
        while True:
            try:
                aplicar_visibilidad(d, "correo")
                try:
                    d.get(URL)                    # actualiza la bandeja (cada minuto)
                    time.sleep(3)
                except Exception:
                    pass
                n = revisar(d, a.debug)
                print(time.strftime("%H:%M:%S"), "correos nuevos:", n)
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "error:", e)
                _LOG.exception("error en el ciclo del lector")
            if a.una:
                break
            time.sleep(a.cada)
    finally:
        d.quit()


if __name__ == "__main__":
    main()
