"""Estado de resultado de una solicitud.

Solo hay tres estados:

* Exitosa      -> el ultimo intento termino bien (en ATP/ONNET «consulta completada» tambien cuenta).
* No exitosa   -> el ultimo intento termino con error, advertencia, cancelacion o sin configurar.
* Escalamiento -> lo marca el operador a mano cuando el caso se escala.

Exitosa / No exitosa se calculan solos al terminar el script; cualquiera de los tres se puede
cambiar a mano (Plantilla o Historial). Los registros viejos se convierten al leerlos
(«Exitosa con historial» -> Exitosa; «Con error», «Cancelada», etc. -> No exitosa).
"""
from __future__ import annotations

EXITOSA = "Exitosa"
ESCALAMIENTO = "Escalamiento"
NO_EXITOSA = "No exitosa"
OPCIONES_MANUALES = (EXITOSA, ESCALAMIENTO, NO_EXITOSA)
ASIGNADA = "Asignada"
SIN_ASIGNAR = "Sin Asignar"

# Como se escribe cada estado en la columna Est_Seg de SharePoint (asi aparece en la lista)
_EN_SP = {EXITOSA: "Exitosa", NO_EXITOSA: "No Exitosa", ESCALAMIENTO: "Escalamiento",
          ASIGNADA: "Asignada", SIN_ASIGNAR: "Sin Asignar"}


def a_sp(estado: str) -> str:
    """Valor exacto para Est_Seg ('No exitosa' -> 'No Exitosa')."""
    e = (estado or "").strip()
    for k, v in _EN_SP.items():
        if e.lower() == k.lower():
            return v
    return e


def es_exitoso(intento: dict) -> bool:
    e = intento.get("estado")
    return e == "exito" or (e == "consulta_sin_config" and intento.get("red") in ("ATP", "ONNET"))


def es_fallido(intento: dict) -> bool:
    return not es_exitoso(intento)


def normalizar(texto: str) -> str:
    """Convierte cualquier estado guardado (incluidos los antiguos) a uno de los tres."""
    t = (texto or "").strip()
    if not t:
        return ""
    if t in OPCIONES_MANUALES:
        return t
    if t.lower().startswith("exitosa"):
        return EXITOSA
    return NO_EXITOSA


def resultado(intentos: list) -> str:
    """'' si todavia no hay ningun intento."""
    if not intentos:
        return ""
    return EXITOSA if es_exitoso(intentos[-1]) else NO_EXITOSA


def resultado_efectivo(intentos: list, manual: str = "") -> str:
    """El estado elegido a mano gana sobre el calculado."""
    return manual if manual in OPCIONES_MANUALES else resultado(intentos)
