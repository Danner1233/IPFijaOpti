# -*- coding: utf-8 -*-
"""Lee la lista de SharePoint 'Solicitud IP Fija FTTx Campo' con SU sesion del navegador (sin Power Automate,
sin permisos de administrador) y mete las solicitudes nuevas en la cola.

Solo toma las solicitudes asignadas a MI nombre (columna PEM_ASIGNADO).
Primera vez:  python sp_lector.py --nombre "Nombre Apellido" --ver      (se abre Chrome: inicie sesion y resuelva el MFA; queda guardado)
Despues:      python sp_lector.py            (vigila la lista cada 6 s, en segundo plano)
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
from hac_zac import cola, presencia, reparto_equipo
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


# Escribe estado (Est_Seg) + causa + observacion de una solicitud, con control de ETag.
# 'campos' ya trae los valores exactos; 'nota' se AGREGA al final de Observaciones (no borra lo que haya).
# Si SharePoint rechaza la causa (columna de opciones con otro texto), se reintenta sin ella y la causa va en la nota.
JS_ESTADO = r"""
const cb = arguments[arguments.length - 1];
const base = arguments[0], ruta = arguments[1], id = arguments[2], campos = arguments[3], nota = arguments[4],
      colsCausa = arguments[5], textoCausa = arguments[6];
(async () => {
  try {
    const h = {'Accept': 'application/json;odata=minimalmetadata'};
    const ci = await fetch(ruta + '/_api/contextinfo', {method: 'POST', headers: h, credentials: 'same-origin'});
    const digest = (await ci.json()).FormDigestValue;
    const item = base + '(' + id + ')';
    const g = await fetch(item, {headers: h, credentials: 'same-origin'});
    const j = await g.json();
    const etag = j['odata.etag'] || g.headers.get('ETag');
    const obsAntes = j.Observaciones || '';
    const merge = (body) => fetch(item, {method: 'POST', credentials: 'same-origin', body: JSON.stringify(body), headers: {
      'Accept': 'application/json;odata=nometadata', 'Content-Type': 'application/json;odata=nometadata',
      'X-RequestDigest': digest, 'IF-MATCH': etag, 'X-HTTP-Method': 'MERGE'}});
    const sep = /<(div|p|br)[\s>\/]/i.test(obsAntes) ? '<br>' : '\n';     // texto enriquecido o simple
    const conNota = (b, n) => { if (n) b.Observaciones = obsAntes ? obsAntes + sep + n : n; return b; };
    let r = await merge(conNota(Object.assign({}, campos), nota));
    let sinCausa = false;
    if (!r.ok && r.status !== 412 && colsCausa.length) {
      const b = Object.assign({}, campos); colsCausa.forEach(c => delete b[c]);
      r = await merge(conNota(b, (nota || '') + (textoCausa ? ' (causa: ' + textoCausa + ')' : '')));
      sinCausa = r.ok;
    }
    cb({ok: r.ok, status: r.status, antes: j.Est_Seg || '', sin_causa: sinCausa,
        motivo: r.ok ? '' : (r.status === 412 ? 'la solicitud cambio en SharePoint mientras tanto' : (await r.text()).slice(0, 200))});
  } catch (e) { cb({ok: false, motivo: String(e)}); }
})();
"""

# Devuelve la solicitud (Sin Asignar): solo si sigue asignada a MI nombre.
JS_LIBERAR = r"""
const cb = arguments[arguments.length - 1];
const base = arguments[0], ruta = arguments[1], id = arguments[2], nombre = arguments[3], nota = arguments[4] || '';
(async () => {
  try {
    const h = {'Accept': 'application/json;odata=minimalmetadata'};
    const ci = await fetch(ruta + '/_api/contextinfo', {method: 'POST', headers: h, credentials: 'same-origin'});
    const digest = (await ci.json()).FormDigestValue;
    const item = base + '(' + id + ')';
    const g = await fetch(item, {headers: h, credentials: 'same-origin'});
    const j = await g.json();
    const pem = String(j.PEM_ASIGNADO || '');
    const plano = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    if (!pem || !plano(nombre).split(/\s+/).every(w => plano(pem).includes(w))) {
      cb({ok: false, motivo: 'ya no esta asignada a usted (PEM: ' + pem + ')', antes: j.Est_Seg || ''}); return;
    }
    const etag = j['odata.etag'] || g.headers.get('ETag');
    const r = await fetch(item, {method: 'POST', credentials: 'same-origin',
      body: JSON.stringify(Object.assign({PEM_ASIGNADO: null, Est_Seg: 'Sin Asignar'}, nota ? {Observaciones:
        (j.Observaciones ? j.Observaciones + (/<(div|p|br)[\s>\/]/i.test(j.Observaciones) ? '<br>' : '\n') : '') + nota}
        : {})), headers: {
      'Accept': 'application/json;odata=nometadata', 'Content-Type': 'application/json;odata=nometadata',
      'X-RequestDigest': digest, 'IF-MATCH': etag, 'X-HTTP-Method': 'MERGE'}});
    cb({ok: r.ok, status: r.status, antes: j.Est_Seg || '', motivo: r.ok ? '' : (await r.text()).slice(0, 200)});
  } catch (e) { cb({ok: false, motivo: String(e)}); }
})();
"""


# ADMIN: pasa la solicitud del PEM 'de' al PEM 'a' (solo si sigue a nombre de 'de'), deja Est_Seg en Asignada y
# agrega la nota en Observaciones.
JS_REASIGNAR = r"""
const cb = arguments[arguments.length - 1];
const base = arguments[0], ruta = arguments[1], id = arguments[2], de = arguments[3], a = arguments[4],
      nota = arguments[5] || '';
(async () => {
  try {
    const h = {'Accept': 'application/json;odata=minimalmetadata'};
    const ci = await fetch(ruta + '/_api/contextinfo', {method: 'POST', headers: h, credentials: 'same-origin'});
    const digest = (await ci.json()).FormDigestValue;
    const item = base + '(' + id + ')';
    const g = await fetch(item, {headers: h, credentials: 'same-origin'});
    const j = await g.json();
    const pem = String(j.PEM_ASIGNADO || '');
    const plano = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    if (!pem || !plano(de).split(/\s+/).every(w => plano(pem).includes(w))) {
      cb({ok: false, motivo: 'ya no esta a nombre de ' + de + ' (PEM: ' + pem + ')', antes: j.Est_Seg || ''}); return;
    }
    const etag = j['odata.etag'] || g.headers.get('ETag');
    const obs = (j.Observaciones ? j.Observaciones + (/<(div|p|br)[\s>\/]/i.test(j.Observaciones) ? '<br>' : '\n') : '') + nota;
    const r = await fetch(item, {method: 'POST', credentials: 'same-origin',
      body: JSON.stringify(Object.assign({PEM_ASIGNADO: a, Est_Seg: 'Asignada'}, nota ? {Observaciones: obs} : {})),
      headers: {'Accept': 'application/json;odata=nometadata', 'Content-Type': 'application/json;odata=nometadata',
                'X-RequestDigest': digest, 'IF-MATCH': etag, 'X-HTTP-Method': 'MERGE'}});
    cb({ok: r.ok, status: r.status, antes: j.Est_Seg || '', motivo: r.ok ? '' : (await r.text()).slice(0, 200)});
  } catch (e) { cb({ok: false, motivo: String(e)}); }
})();
"""


def nota_reasignar(por, de, a, ahora=None):
    from datetime import datetime
    return "[%s] Admin %s: reasignó la solicitud de %s a %s" % ((ahora or datetime.now()).strftime("%d/%m %H:%M"),
                                                               por, de, a)


def enviar_reasignaciones(driver):
    """ADMIN: reasignaciones pedidas en la pestana Admin."""
    n = 0
    for id_, p in cola.reasignar_pendientes().items():
        try:
            r = driver.execute_async_script(JS_REASIGNAR, BASE_ITEMS, RUTA_SITIO, id_, p["de"], p["a"],
                                            nota_reasignar(p.get("por", ""), p["de"], p["a"]))
        except Exception as e:
            r = {"ok": False, "motivo": str(e)}
        cola.resultado_reasignar(id_, r.get("ok"), r.get("motivo", ""))
        cola.registrar_escritura_sp(id_, "PEM_ASIGNADO", p["de"], p["a"], r.get("ok"), r.get("motivo", ""),
                                    est_seg="Asignada")
        if r.get("ok"):
            print("   [admin] solicitud %s reasignada de %s a %s" % (id_, p["de"], p["a"]))
            n += 1
        else:
            print("   [admin] no pude reasignar la %s: %s" % (id_, r.get("motivo")))
    return n


def cambios_estado(estado, causa="", observacion="", pem="", ahora=None):
    """(campos, nota, columnas_de_causa) para JS_ESTADO. La causa va en la columna de su estado y se limpia la del
    otro estado; con Exitosa se limpian las dos. La nota (para Observaciones) solo si hay causa u observacion."""
    from datetime import datetime
    from hac_zac import causas, estados
    est = estados.normalizar(estado) or estado
    campos = {"Est_Seg": estados.a_sp(est)}
    cols = []
    if est in causas.COLUMNA or est == estados.EXITOSA:
        for e, col in causas.COLUMNA.items():
            campos[col] = (causa or None) if e == est else None
            if e == est and causa:
                cols.append(col)
    nota = ""
    if causa or (observacion or "").strip():
        partes = [estados.a_sp(est)] + ([causa] if causa else [])
        nota = "[%s] PEM %s: %s" % ((ahora or datetime.now()).strftime("%d/%m %H:%M"), pem or "-", " · ".join(partes))
        if (observacion or "").strip():
            nota += " — " + " ".join(observacion.split())
    return campos, nota, cols


def enviar_estados_pendientes(driver):
    """Escribe en SharePoint estado + causa + observacion de las solicitudes. Devuelve cuantas escribio."""
    n = 0
    for id_, p in cola.pendientes_sp_detalle().items():
        if cola.es_del_central(id_):
            continue                                  # su Est_Seg lo escribe el servidor central
        estado = p["est_seg"]
        campos, nota, cols = cambios_estado(estado, p.get("causa", ""), p.get("observacion", ""), p.get("pem", ""))
        try:
            r = driver.execute_async_script(JS_ESTADO, BASE_ITEMS, RUTA_SITIO, id_, campos, nota, cols,
                                            p.get("causa", ""))
        except Exception as e:
            r = {"ok": False, "motivo": str(e)}
        cola.resultado_sp(id_, r.get("ok"), r.get("motivo", ""))
        cola.registrar_escritura_sp(id_, "Est_Seg", r.get("antes", ""), campos["Est_Seg"], r.get("ok"),
                                    r.get("motivo", ""), causa=p.get("causa", ""), nota=nota,
                                    causa_en_observacion=bool(r.get("sin_causa")))
        if r.get("ok"):
            print("   solicitud %s: '%s'%s escrito en SharePoint" % (
                id_, campos["Est_Seg"], (" (" + p["causa"] + ")") if p.get("causa") else ""))
            if r.get("sin_causa"):
                _LOG.warning("SP %s: la columna de causa no acepto %r; quedo en Observaciones", id_, p.get("causa"))
            n += 1
        else:
            print("   no pude escribir el estado de la %s: %s" % (id_, r.get("motivo")))
            _LOG.error("estado SP %s -> %s fallo: %s", id_, estado, r.get("motivo"))
    return n


def enviar_liberaciones(driver):
    """Solicitudes que el PEM devolvio: PEM_ASIGNADO vacio y Est_Seg = Sin Asignar."""
    n = 0
    for id_, p in cola.liberar_pendientes().items():
        try:
            from datetime import datetime
            from hac_zac import reparto_equipo
            nota = "[%s] PEM %s: liberó la solicitud" % (datetime.now().strftime("%d/%m %H:%M"), p.get("pem", ""))
            assert reparto_equipo.NOTA_LIBERO in cola._plano(nota)     # el reparto la reconoce y no se la devuelve
            r = driver.execute_async_script(JS_LIBERAR, BASE_ITEMS, RUTA_SITIO, id_, p.get("pem", ""), nota)
        except Exception as e:
            r = {"ok": False, "motivo": str(e)}
        cola.resultado_liberar(id_, r.get("ok"), r.get("motivo", ""))
        cola.registrar_escritura_sp(id_, "PEM_ASIGNADO", p.get("pem", ""), "", r.get("ok"), r.get("motivo", ""),
                                    est_seg="Sin Asignar")
        if r.get("ok"):
            print("   solicitud %s liberada (Sin Asignar)" % id_)
            n += 1
        else:
            print("   no pude liberar la %s: %s" % (id_, r.get("motivo")))
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


def es_admin_repartiendo(aj):
    return bool(aj.get("rol_admin") and aj.get("admin_repartir"))


def repartir_equipo(driver, items, aj, log=print):
    """ROL ADMIN: reparte las libres entre los PEM de la lista (activos por el admin y Activos en la app), una a
    la vez y por turno. Publica la lista en la carpeta del equipo para que esos PEM no se autoasignen.
    En simulacion solo muestra a quien asignaria (y no publica). Devuelve las asignadas [(id, nombre)]."""
    from datetime import datetime
    if not es_admin_repartiendo(aj):
        return []
    carpeta = aj.get("carpeta_equipo", "")
    simular = bool(aj.get("admin_simular"))
    if not carpeta:
        log("   [admin] falta la carpeta del equipo en Ajustes: no se puede ver quien esta en linea")
        return []
    yo = aj.get("pem_nombre", "")
    if not simular and not reparto_equipo.debo_repartir(carpeta, yo):
        otro, s = reparto_equipo.quien_reparte(carpeta)
        log("   [admin] reparte %s (hace %d s): usted queda de respaldo" % (otro, s or 0))
        return []
    roster = reparto_equipo.roster(carpeta)
    plan = reparto_equipo.plan(items, roster, reparto_equipo.presencia_por_nombre(carpeta))
    hechas = []
    for it, nombre in plan:
        if simular:
            log("   [admin simulacion] solicitud %s -> %s" % (it.get("ID"), nombre))
            continue
        if asignar_item(driver, it, nombre):
            hechas.append((str(it.get("ID")), nombre))
            for p in roster:
                if p["nombre"] == nombre:
                    p["ultimo"] = datetime.now().isoformat(timespec="seconds")
            log("   [admin] solicitud %s asignada a %s" % (it.get("ID"), nombre))
    if hechas:
        reparto_equipo.guardar_roster(carpeta, roster)
    if not simular:
        try:
            reparto_equipo.publicar(carpeta, roster, yo, respaldo=aj.get("admin_respaldo", True))
        except OSError as e:
            log("   [admin] no pude publicar el reparto en la carpeta del equipo: %s" % e)
    return hechas


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


CADA_S = 6          # cada vuelta: lee la lista (REST), reparte (admin) y ve si me asignaron algo
REFRESCAR_S = 300   # la pagina solo se recarga cada 5 min (la lectura es por REST: no necesita recargar)
MAX_HORAS = 24      # no importa solicitudes mias mas viejas que esto (ya no son "las de ahora")


TOMADAS = set()          # IDs que este lector se autoasigno (para el reporte: origen)


def origen_de(id_):
    """auto si me la tome yo; admin si el admin esta repartiendo y me incluye; si no, sharepoint."""
    if str(id_) in TOMADAS:
        return "auto"
    try:
        aj = cola._leer("ajustes.json", {})
        if reparto_equipo.lo_reparte_el_admin(aj.get("carpeta_equipo", ""), cola.nombre_configurado()):
            return "admin"
    except Exception:
        pass
    return "sharepoint"


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
            cola.poner_origen(d["id"], origen_de(d["id"]))
            nuevas += 1
    return nuevas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true", help="mostrar el navegador (para iniciar sesion)")
    ap.add_argument("--una", action="store_true", help="leer una sola vez")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--archivo", help="usar un JSON de items en vez del navegador")
    ap.add_argument("--cada", type=int, default=CADA_S, help="segundos entre vueltas (por defecto %d)" % CADA_S)
    ap.add_argument("--tomar", action="store_true", help="(ya no se usa: solo asignan los administradores)")
    ap.add_argument("--simular", action="store_true", help="(ya no se usa)")
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
    recargada = time.time()
    try:
        while True:
            try:
                aplicar_visibilidad(d, "sp")
                if enviar_estados_pendientes(d) + enviar_liberaciones(d) + enviar_reasignaciones(d):
                    time.sleep(1)
                items = leer_items(d, a.debug)
                aj = cola._leer("ajustes.json", {})
                if repartir_equipo(d, items, aj):          # rol admin: reparte entre los PEM activos y en linea
                    items = leer_items(d)
                for sid in cola.soltar_si_ya_no_es_mia(items, nombre):
                    print("   la solicitud %s ya no es mia (el admin la reasigno): sale de mi cola" % sid)
                # Asignan los administradores (pestana Admin). RESPALDO: si ningun admin reparte en 5 min, el PEM en
                # turno y activo en la lista se autoasigna una a la vez (SharePoint evita las dobles).
                carpeta = aj.get("carpeta_equipo", "")
                if not presencia.mi_pausa() and reparto_equipo.respaldo_activo(carpeta, nombre):
                    abiertas = cola.mis_casos(nombre)
                    sin_cerrar = cola.abiertas_sp(items, nombre, MAX_HORAS)
                    libres = [x for x in items if cola.es_libre(x)]
                    if not abiertas and not sin_cerrar and libres:
                        print("   [respaldo] ningun admin reparte hace %d min: tomo la mas antigua"
                              % reparto_equipo.RESPALDO_MIN)
                        tomada = tomar_libre(d, items, nombre, a.simular)
                        if tomada:
                            TOMADAS.add(str(tomada))
                            items = leer_items(d)
                n = procesar(items, nombre)
                print(time.strftime("%H:%M:%S"), "mis solicitudes nuevas:", n)
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "error:", e)
                _LOG.exception("error en el ciclo del lector")
                recargada = 0                         # tras un error se recarga ya (p. ej. la sesion vencio)
            if a.una:
                break
            if time.time() - recargada >= REFRESCAR_S:
                try:
                    d.refresh()                       # mantiene viva la sesion; la lectura no lo necesita
                except Exception:
                    pass
                recargada = time.time()
            time.sleep(a.cada)
    finally:
        d.quit()


if __name__ == "__main__":
    main()
