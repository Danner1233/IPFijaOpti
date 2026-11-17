# -*- coding: utf-8 -*-
"""Lee la lista de SharePoint 'Solicitud IP Fija FTTx Campo' con SU sesion del navegador (sin Power Automate,
sin permisos de administrador) y mete las solicitudes nuevas en la cola.

Solo toma las solicitudes asignadas a MI nombre (columna PEM_ASIGNADO).
Primera vez:  python sp_lector.py --nombre "Nombre Apellido" --ver      (se abre Chrome: inicie sesion y resuelva el MFA; queda guardado)
Despues:      python sp_lector.py            (vigila la lista cada 20 s, en segundo plano)
Una vez:      python sp_lector.py --una --debug   (guarda sp_debug.json con los datos crudos)
Prueba:       python sp_lector.py --archivo items.json   (sin navegador)

Requiere: pip install selenium
"""
import argparse
import json
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from hac_zac import cola
from hac_zac import log as _log

_LOG = _log.obtener('sp_lector')  # noqa: E402

SITIO = "https://claromovilco.sharepoint.com/sites/instalacioneseyn/Seguimiento_Expertos"
RUTA_SITIO = "/sites/instalacioneseyn/Seguimiento_Expertos"
LISTA = "Solicitud IP Fija FTTx Campo"
# Fuera de OneDrive: OneDrive sincroniza/bloquea la carpeta de sesion de Chrome y Chrome no arranca.
PERFIL = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "perfil_sp")
VISTA = SITIO + "/Lists/A%20Seguimiento%20Compromiso/Asignar%20PEM%202.aspx"   # pagina de la lista (mismo origen)
# Dos formas de llegar a la misma lista; si la primera da 404 se prueba la segunda.
APIS = [
    RUTA_SITIO + "/_api/web/GetList('" + RUTA_SITIO + "/Lists/A Seguimiento Compromiso')/items?$top=60&$orderby=Created desc",
    RUTA_SITIO + "/_api/web/lists/getbytitle('" + LISTA + "')/items?$top=60&$orderby=Created desc",
]

JS = """
const cb = arguments[arguments.length - 1];
fetch(arguments[0], {headers: {'Accept': 'application/json;odata=nometadata'}, credentials: 'same-origin'})
  .then(r => r.text().then(t => cb({status: r.status, texto: t})))
  .catch(e => cb({status: 0, texto: String(e)}));
"""


def abrir(ver=True):
    """Se ve u oculta segun Ajustes > Ver navegador (por defecto se ve)."""
    from navegador import abrir_navegador
    d = abrir_navegador(PERFIL, "1300,850", log=lambda m: print(m, flush=True), proceso="sp")
    d.set_script_timeout(60)
    d.get(VISTA)
    return d


BASE_ITEMS = RUTA_SITIO + "/_api/web/GetList('" + RUTA_SITIO + "/Lists/A Seguimiento Compromiso')/items"

# Escribe MI nombre en PEM_ASIGNADO de una solicitud libre. Antes vuelve a leerla y usa su ETag:
# si otro ingeniero la tomo mientras tanto, SharePoint responde 412 y NO se pisa.
JS_TOMAR = """
const cb = arguments[arguments.length - 1];
const base = arguments[0], ruta = arguments[1], id = arguments[2], nombre = arguments[3], estado = arguments[4];
(async () => {
  try {
    const h = {'Accept': 'application/json;odata=minimalmetadata'};
    const ci = await fetch(ruta + '/_api/contextinfo', {method: 'POST', headers: h, credentials: 'same-origin'});
    const digest = (await ci.json()).FormDigestValue;
    const item = base + '(' + id + ')';
    const g = await fetch(item, {headers: h, credentials: 'same-origin'});
    const j = await g.json();
    if (j.PEM_ASIGNADO) { cb({ok: false, motivo: 'ya la tomo otro: ' + JSON.stringify(j.PEM_ASIGNADO)}); return; }
    const etag = j['odata.etag'] || g.headers.get('ETag');
    const merge = (body) => fetch(item, {method: 'POST', credentials: 'same-origin', body: JSON.stringify(body), headers: {
      'Accept': 'application/json;odata=nometadata', 'Content-Type': 'application/json;odata=nometadata',
      'X-RequestDigest': digest, 'IF-MATCH': etag, 'X-HTTP-Method': 'MERGE'}});
    let r = await merge(estado ? {PEM_ASIGNADO: nombre, Est_Seg: estado} : {PEM_ASIGNADO: nombre});
    if (!r.ok && estado && r.status !== 412) r = await merge({PEM_ASIGNADO: nombre});   // Est_Seg no editable
    cb({ok: r.ok, status: r.status, antes: j.Est_Seg || '', motivo: r.ok ? '' : (r.status === 412 ? 'otro ingeniero la tomo primero' : (await r.text()).slice(0, 200))});
  } catch (e) { cb({ok: false, motivo: String(e)}); }
})();
"""


# Escribe SOLO el estado (Est_Seg) de una solicitud, con control de ETag.
JS_ESTADO = """
const cb = arguments[arguments.length - 1];
const base = arguments[0], ruta = arguments[1], id = arguments[2], estado = arguments[3];
(async () => {
  try {
    const h = {'Accept': 'application/json;odata=minimalmetadata'};
    const ci = await fetch(ruta + '/_api/contextinfo', {method: 'POST', headers: h, credentials: 'same-origin'});
    const digest = (await ci.json()).FormDigestValue;
    const item = base + '(' + id + ')';
    const g = await fetch(item, {headers: h, credentials: 'same-origin'});
    const j = await g.json();
    const etag = j['odata.etag'] || g.headers.get('ETag');
    const r = await fetch(item, {method: 'POST', credentials: 'same-origin', body: JSON.stringify({Est_Seg: estado}), headers: {
      'Accept': 'application/json;odata=nometadata', 'Content-Type': 'application/json;odata=nometadata',
      'X-RequestDigest': digest, 'IF-MATCH': etag, 'X-HTTP-Method': 'MERGE'}});
    cb({ok: r.ok, status: r.status, antes: j.Est_Seg || '', motivo: r.ok ? '' : (await r.text()).slice(0, 200)});
  } catch (e) { cb({ok: false, motivo: String(e)}); }
})();
"""


def enviar_estados_pendientes(driver):
    """Escribe en SharePoint el estado de las solicitudes ya documentadas. Devuelve cuantas escribio."""
    n = 0
    for id_, estado in cola.pendientes_sp().items():
        try:
            r = driver.execute_async_script(JS_ESTADO, BASE_ITEMS, RUTA_SITIO, id_, estado)
        except Exception as e:
            r = {"ok": False, "motivo": str(e)}
        cola.resultado_sp(id_, r.get("ok"), r.get("motivo", ""))
        cola.registrar_escritura_sp(id_, "Est_Seg", r.get("antes", ""), estado, r.get("ok"), r.get("motivo", ""))
        if r.get("ok"):
            print("   solicitud %s: estado '%s' escrito en SharePoint" % (id_, estado))
            n += 1
        else:
            print("   no pude escribir el estado de la %s: %s" % (id_, r.get("motivo")))
            _LOG.error("estado SP %s -> %s fallo: %s", id_, estado, r.get("motivo"))
    return n


def asignar_item(driver, it, nombre, simular=False):
    """Escribe 'nombre' en PEM_ASIGNADO de ese item (con control de ETag). Devuelve el ID o None."""
    if simular:
        print("   [simulacion] asignaria la solicitud", it["ID"], "a", nombre)
        return None
    r = driver.execute_async_script(JS_TOMAR, BASE_ITEMS, RUTA_SITIO, it["ID"], nombre, "Asignada")
    cola.registrar_escritura_sp(it["ID"], "PEM_ASIGNADO", "", nombre, r.get("ok"), r.get("motivo", ""),
                                antes_est=r.get("antes", ""))
    if r.get("ok"):
        print("   solicitud", it["ID"], "asignada a", nombre)
        return it["ID"]
    print("   no pude asignar la", it["ID"], "a", nombre, "->", r.get("motivo"))
    return None


def tomar_libre(driver, items, nombre, simular=False):
    """Me asigno a mi nombre la solicitud libre mas antigua. Devuelve el ID o None."""
    it = cola.elegir_libre(items)
    return asignar_item(driver, it, nombre, simular) if it else None


def url_es_sharepoint(url):
    try:
        return url.split("/")[2].lower() == "claromovilco.sharepoint.com"
    except Exception:
        return False


def en_sharepoint(driver):
    """La peticion solo funciona si la ventana esta en claromovilco.sharepoint.com (mismo origen)."""
    try:
        return driver.current_url.split("/")[2].lower() == "claromovilco.sharepoint.com"
    except Exception:
        return False


def leer_items(driver, debug=False):
    if not en_sharepoint(driver):
        driver.get(VISTA)
        time.sleep(4)
        import ms_login
        from hac_zac import credenciales
        cr = credenciales.cargar()
        ms_login.asegurar_sesion(driver, url_es_sharepoint, cr.get("ms_usuario", ""), cr.get("ms_clave", ""), espera_max=120)
        if not en_sharepoint(driver):
            raise RuntimeError("La ventana no esta en SharePoint (esta en %s). Inicie sesion en la ventana "
                               "y deje abierta la lista." % driver.current_url[:80])
    ultimo = None
    for api in APIS:
        r = driver.execute_async_script(JS, api)
        if r["status"] == 200:
            items = json.loads(r["texto"]).get("value", [])
            if debug:
                with open(os.path.join(AQUI, "sp_debug.json"), "w", encoding="utf-8") as f:
                    json.dump(items[:5], f, ensure_ascii=False, indent=2)
            return items
        ultimo = r
    raise RuntimeError("SharePoint respondio %s: %s (pagina: %s)" % (ultimo["status"], ultimo["texto"][:200],
                                                                    driver.current_url[:80]))


MAX_HORAS = 24      # no importa solicitudes mias mas viejas que esto (ya no son "las de ahora")


def procesar(items, nombre):
    """Solo toma las solicitudes asignadas a mi nombre (PEM_ASIGNADO), abiertas y recientes."""
    from datetime import datetime
    nuevas = 0
    for it in items:
        d = cola.desde_sp(it)
        creada = cola._a_local(d.get("creada"))
        if creada and (datetime.now() - creada).total_seconds() > MAX_HORAS * 3600:
            continue
        if cola.es_mia(d, nombre) and cola.registrar_mia(d, nombre):
            print("   solicitud mia:", d["id"], "RR", d["rr"])
            nuevas += 1
    return nuevas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true", help="mostrar el navegador (para iniciar sesion)")
    ap.add_argument("--una", action="store_true", help="leer una sola vez")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--archivo", help="usar un JSON de items en vez del navegador")
    ap.add_argument("--cada", type=int, default=20)
    ap.add_argument("--tomar", action="store_true", help="asignarme solo una solicitud libre cuando no tengo ninguna")
    ap.add_argument("--simular", action="store_true", help="con --tomar: solo mostrar cual me asignaria, sin escribir")
    ap.add_argument("--nombre", help="mi nombre como aparece en PEM_ASIGNADO (si no, ajustes.json: pem_nombre)")
    a = ap.parse_args()
    nombre = (a.nombre or cola.nombre_configurado()).strip()
    if not nombre:
        sys.exit('Falta mi nombre en SharePoint. Use:  python sp_lector.py --nombre "Nombre Apellido"  '
                 "o guardelo en Ajustes de la aplicacion.")

    if a.archivo:
        with open(a.archivo, encoding="utf-8") as f:
            print(procesar(json.load(f), nombre))
        return

    d = abrir(a.ver)
    import ms_login
    from hac_zac import credenciales
    cr = credenciales.cargar()
    from navegador import aplicar_visibilidad
    if not ms_login.asegurar_sesion(d, url_es_sharepoint, cr.get("ms_usuario", ""), cr.get("ms_clave", ""),
                                    mostrar=lambda: aplicar_visibilidad(d, "sp", True)):
        print("No se pudo iniciar sesion en SharePoint en 5 minutos; se intentara en cada ciclo.")
    try:
        while True:
            try:
                aplicar_visibilidad(d, "sp")
                if enviar_estados_pendientes(d):
                    time.sleep(1)
                items = leer_items(d, a.debug)
                if a.tomar or cola.auto_asignar_configurado():
                    abiertas = cola.mis_casos(nombre)
                    sin_cerrar = cola.abiertas_sp(items, nombre, MAX_HORAS)
                    libres = [x for x in items if cola.es_libre(x)]
                    if abiertas:
                        print("   ya tengo la solicitud %s en curso: no tomo otra" % abiertas[0]["id"])
                    elif sin_cerrar:
                        print("   la solicitud %s sigue sin documentar (en SharePoint no esta Exitosa / No exitosa / "
                              "Escalamiento): no tomo otra" % sin_cerrar[0])
                    elif not libres:
                        print("   leidas %d solicitudes; ninguna con PEM_ASIGNADO vacio" % len(items))
                    else:
                        print("   hay %d libre(s); tomo la mas antigua" % len(libres))
                        if tomar_libre(d, items, nombre, a.simular):
                            items = leer_items(d)         # releer para ver mi asignacion
                n = procesar(items, nombre)
                print(time.strftime("%H:%M:%S"), "mis solicitudes nuevas:", n)
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "error:", e)
                _LOG.exception("error en el ciclo del lector")
            if a.una:
                break
            try:
                d.refresh()                           # recarga la pagina cada vuelta (cada 20 s)
            except Exception:
                pass
            time.sleep(a.cada)
    finally:
        d.quit()


if __name__ == "__main__":
    main()
