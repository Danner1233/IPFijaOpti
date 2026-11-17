# -*- coding: utf-8 -*-
"""Cifrado de credenciales con DPAPI de Windows (el mismo que usan Chrome y el Administrador de credenciales).

- Solo SU usuario de Windows, en SU PC, puede descifrar. Si alguien copia credenciales.json a otro PC o lo sube
  a internet, no sirve.
- Sin dependencias (ctypes) y compatible con Python 3 (interfaz, lectores) y Python 2.7 (SecureCRT).

Los valores cifrados se guardan como "dpapi:<base64>". Un valor sin ese prefijo se toma como texto plano
(archivos viejos); la interfaz lo vuelve a guardar cifrado.
"""
import base64
import sys

PREFIJO = "dpapi:"
_ENTROPIA = b"hac_zac-credenciales-v1"


def disponible():
    if sys.platform != "win32":
        return False
    try:
        import ctypes  # noqa: F401
        from ctypes import wintypes  # noqa: F401
        return True
    except Exception:
        return False


def _api():
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(datos):
        buf = ctypes.create_string_buffer(datos, len(datos))
        return BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def leer(b):
        try:
            return ctypes.string_at(b.pbData, b.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(b.pbData)

    return ctypes, BLOB, blob, leer


def _a_bytes(texto):
    if isinstance(texto, bytes):
        return texto
    return texto.encode("utf-8")


def cifrar(texto):
    """Texto -> 'dpapi:<base64>'. Vacio queda vacio."""
    if not texto:
        return ""
    ctypes, BLOB, blob, leer = _api()
    entrada, _b1 = blob(_a_bytes(texto))
    entropia, _b2 = blob(_ENTROPIA)
    salida = BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
                                                  CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida)):
        raise OSError("CryptProtectData fallo (error %d)" % ctypes.GetLastError())
    return PREFIJO + base64.b64encode(leer(salida)).decode("ascii")


def descifrar(valor):
    """'dpapi:<base64>' -> texto (unicode). Texto sin prefijo se devuelve igual (archivos viejos)."""
    if not valor:
        return u""
    if not valor.startswith(PREFIJO):
        return valor
    ctypes, BLOB, blob, leer = _api()
    entrada, _b1 = blob(base64.b64decode(valor[len(PREFIJO):]))
    entropia, _b2 = blob(_ENTROPIA)
    salida = BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
                                                    0x01, ctypes.byref(salida)):
        raise OSError("No se pudo descifrar (otro usuario de Windows u otro PC). Vuelva a escribirla en Ajustes.")
    return leer(salida).decode("utf-8")


def es_cifrado(valor):
    return bool(valor) and valor.startswith(PREFIJO)
