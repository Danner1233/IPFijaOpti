"""Credenciales del Support Portal, de SecureCRT (equipos) y de Microsoft. Se guardan en credenciales.json, en la
carpeta de datos. Las CLAVES van cifradas con DPAPI de Windows (solo su usuario, en su PC, puede leerlas); los
usuarios van en claro. El script de SecureCRT las lee y descifra en cada ejecucion.

Nunca se escriben credenciales en el codigo ni en el repositorio."""
import json
import logging
import os
import sys

from .rutas import data_dir

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hac_zac_dpapi as dpapi  # noqa: E402

CAMPOS = ("portal_usuario", "portal_clave", "crt_usuario", "crt_clave", "ms_usuario", "ms_clave")
CLAVES = tuple(k for k in CAMPOS if k.endswith("_clave"))
_LOG = logging.getLogger("hac_zac.credenciales")


def ruta():
    return data_dir() / "credenciales.json"


def _leer_archivo() -> dict:
    try:
        return json.loads(ruta().read_text(encoding="utf-8"))
    except Exception:
        return {}


def cargar() -> dict:
    """Credenciales en claro (para usarlas). Si el archivo tiene claves viejas sin cifrar, lo cifra."""
    datos = _leer_archivo()
    out = {}
    hay_planas = False
    for k in CAMPOS:
        v = str(datos.get(k, "") or "")
        if k in CLAVES and v:
            if dpapi.es_cifrado(v):
                try:
                    v = dpapi.descifrar(v)
                except Exception as e:
                    _LOG.warning("no pude descifrar %s: %s", k, e)
                    v = ""
            else:
                hay_planas = True
        out[k] = v
    if hay_planas and dpapi.disponible():
        try:
            guardar(out)
        except Exception as e:
            _LOG.warning("no pude cifrar credenciales viejas: %s", e)
    return out


def guardar(valores: dict) -> None:
    datos = {}
    for k in CAMPOS:
        v = str(valores.get(k, "") or "").strip()
        if k in CLAVES and v and dpapi.disponible():
            v = dpapi.cifrar(v)
        datos[k] = v
    tmp = ruta().with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta())
