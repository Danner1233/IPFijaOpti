# -*- coding: utf-8 -*-
"""Agente que atiende al TECNICO por WhatsApp para que el PEM no tenga que hablar con el.

BARRERAS EN CODIGO (no dependen del modelo):
* La IA solo CLASIFICA el mensaje del tecnico en una intencion de la lista INTENCIONES. Nunca redacta lo que se
  le envia: todas las respuestas son textos de este archivo armados con datos reales del caso.
* El direccionamiento / IP y las observaciones se reenvian LITERALES tal como los escribio el PEM. Si el PEM aun
  no los envio, se dice eso; jamas se deduce ni se inventa una IP.
* Un tecnico solo ve SU caso: se identifica por el celular registrado en la solicitud (celular_tecnico).
* A la IA solo le llega el texto del tecnico (sin nombre de cliente, cuenta ni IPs).
* Lo que el agente no sabe responder se le pasa al PEM como nota en su aplicacion.

Logica pura: recibe el estado del central y devuelve los mensajes a enviar [(telefono, texto)].
"""
import re
from datetime import datetime, timedelta

from . import cola

INTENCIONES = ("saludo", "estado", "direccionamiento", "confirmar_si", "confirmar_no", "otro")
HORAS_CHAT = 24                  # tras documentar, el tecnico puede seguir escribiendo este tiempo sobre ese caso


# ---------------------------------------------------------------------------------------------- telefonos
def telefono(x):
    """Celular colombiano -> formato WhatsApp (solo digitos con 57). '300 123 4567' -> '573001234567'."""
    d = "".join(ch for ch in str(x or "") if ch.isdigit())
    if len(d) == 10 and d.startswith("3"):
        d = "57" + d
    return d


def _iso(d):
    return d.isoformat(timespec="seconds")


def _anotar(a, de, texto, ahora, **extra):
    m = {"de": de, "texto": texto, "hora": _iso(ahora)}
    m.update(extra)
    a.setdefault("chat", []).append(m)
    return m


def caso_de_telefono(estado, tel, ahora):
    """(id, asignacion) del caso de ese tecnico: el abierto mas reciente o, si no hay, uno cerrado hace poco."""
    tel = telefono(tel)
    if not tel:
        return None, None
    abiertos, recientes = [], []
    for i, a in estado["asignaciones"].items():
        if telefono(a["datos"].get("celular_tecnico")) != tel:
            continue
        if not a.get("cerrada_en"):
            abiertos.append((a["asignada_en"], i, a))
        else:
            try:
                if ahora - datetime.fromisoformat(a["cerrada_en"]) <= timedelta(hours=HORAS_CHAT):
                    recientes.append((a["cerrada_en"], i, a))
            except ValueError:
                pass
    for grupo in (abiertos, recientes):
        if grupo:
            _, i, a = max(grupo)
            return i, a
    return None, None


# ---------------------------------------------------------------------------------------------- reglas
_SI = re.compile(r"^\s*(si|sí|s|ok|okay|listo|correcto|todo bien|todo ok|quedo|quedó|perfecto|funciona|ya)\b", re.I)
_NO = re.compile(r"^\s*(no|n|aun no|aún no|todavia no|todavía no|falla|no funciona|no sirve|no quedo|no quedó)\b", re.I)


def clasificar_reglas(texto, esperando_confirmacion=False):
    t = cola._plano(texto)
    if esperando_confirmacion:
        if _NO.match(t):
            return "confirmar_no"
        if _SI.match(t):
            return "confirmar_si"
    if re.search(r"\b(ip|direccion|direccionamiento|gateway|gw|mascara|segmento|dns)\b", t):
        return "direccionamiento"
    if re.search(r"\b(estado|como va|cuanto|demora|falta|ya quedo|avance|novedad|listo)\b", t):
        return "estado"
    if re.fullmatch(r"(hola|buenas|buenos dias|buenas tardes|buenas noches|hey|saludos)[ !.]*", t):
        return "saludo"
    return "otro"


# ---------------------------------------------------------------------------------------------- textos
def _nombre_tecnico(a):
    n = str(a["datos"].get("tecnico") or "").strip().split()
    return n[0].capitalize() if n else ""


def texto_asignacion(i, a):
    d = a["datos"]
    hola = ("Hola %s. " % _nombre_tecnico(a)) if _nombre_tecnico(a) else "Hola. "
    return (hola + "Soy el asistente de Puesta en Marcha. Tu solicitud de IP fija %s (cuenta RR %s) ya la tiene "
            "un ingeniero y está en proceso. Por aquí te aviso el resultado y te paso el direccionamiento. "
            "Puedes escribirme si necesitas algo." % (i, d.get("rr") or "-"))


def texto_estado(i, a):
    if a.get("cerrada_en"):
        return "Tu solicitud %s ya fue cerrada como: %s." % (i, a.get("estado") or "-")
    if a.get("direccionamiento"):
        return "Tu solicitud %s está en proceso y el ingeniero ya envió el direccionamiento." % i
    return "Tu solicitud %s está en proceso con el ingeniero. Te aviso por aquí apenas haya novedad." % i


def texto_direccionamiento(i, a):
    if a.get("direccionamiento"):
        return "Direccionamiento de la solicitud %s (enviado por el ingeniero):\n\n%s" % (i, a["direccionamiento"])
    return ("El ingeniero todavía no ha enviado el direccionamiento de la solicitud %s. Te lo paso apenas lo tenga."
            % i)


def texto_cierre(i, est):
    e = cola._plano(est)
    if e == "exitosa":
        return ("La solicitud %s quedó EXITOSA. ¿Quedó todo en orden con el servicio? Responde SI o NO "
                "(si es NO, cuéntame qué pasa)." % i)
    return "La solicitud %s quedó como: %s. Si tienes dudas, escríbeme y se las paso al ingeniero." % (i, est)


# ---------------------------------------------------------------------------------------------- eventos
def al_asignar(estado, id_, ahora):
    """Aviso al tecnico cuando su solicitud se asigna. [(tel, texto)]"""
    a = estado["asignaciones"][str(id_)]
    tel = telefono(a["datos"].get("celular_tecnico"))
    if not tel:
        return []
    t = texto_asignacion(id_, a)
    _anotar(a, "agente", t, ahora)
    return [(tel, t)]


def mensaje_pem(estado, id_, pem, texto, tipo, ahora):
    """El PEM escribe desde su aplicacion. Se reenvia LITERAL. tipo: 'mensaje' u 'direccionamiento'.
    Devuelve [(tel, texto)]; ValueError si el caso no es de ese PEM o no hay celular."""
    a = estado["asignaciones"].get(str(id_))
    if not a or a["pem"] != pem:
        raise ValueError("Ese caso no está asignado a usted.")
    texto = str(texto or "").strip()
    if not texto:
        raise ValueError("Escriba el mensaje.")
    tel = telefono(a["datos"].get("celular_tecnico"))
    if not tel:
        raise ValueError("La solicitud no trae celular del técnico.")
    if tipo == "direccionamiento":
        a["direccionamiento"] = texto
        salida = "Direccionamiento de la solicitud %s (enviado por el ingeniero):\n\n%s" % (id_, texto)
    else:
        salida = "Mensaje del ingeniero sobre la solicitud %s:\n\n%s" % (id_, texto)
    _anotar(a, "pem", texto, ahora, tipo=tipo)
    a["para_pem"] = []                               # al responder, lo pendiente del tecnico queda atendido
    return [(tel, salida)]


def al_documentar(estado, id_, est, ahora):
    a = estado["asignaciones"].get(str(id_))
    if not a or a.get("cierre_avisado"):
        return []
    tel = telefono(a["datos"].get("celular_tecnico"))
    a["cierre_avisado"] = True
    if not tel:
        return []
    t = texto_cierre(id_, est)
    a["esperando_confirmacion"] = cola._plano(est) == "exitosa"
    _anotar(a, "agente", t, ahora)
    return [(tel, t)]


def mensaje_tecnico(estado, tel, texto, ahora, clasificar=None):
    """Mensaje que llega del tecnico. Devuelve [(tel, respuesta)]. `clasificar(texto, esperando)` -> intencion
    (la IA); si falla o devuelve algo fuera de INTENCIONES se usan las reglas."""
    tel = telefono(tel)
    i, a = caso_de_telefono(estado, tel, ahora)
    if a is None:
        return [(tel, "Hola. No encuentro una solicitud de IP fija activa para este número. Si acabas de crearla, "
                      "espera unos minutos; si no, confirma que tu celular esté bien escrito en la solicitud.")]
    _anotar(a, "tecnico", texto, ahora)
    esperando = bool(a.get("esperando_confirmacion"))
    intencion = None
    if clasificar:
        try:
            intencion = clasificar(texto, esperando)
        except Exception:
            intencion = None
    if intencion not in INTENCIONES:
        intencion = clasificar_reglas(texto, esperando)
    if intencion in ("confirmar_si", "confirmar_no") and not esperando:
        intencion = "otro"

    if intencion == "saludo":
        r = "Hola. " + texto_estado(i, a)
    elif intencion == "estado":
        r = texto_estado(i, a)
    elif intencion == "direccionamiento":
        r = texto_direccionamiento(i, a)
        if not a.get("direccionamiento"):
            _para_pem(a, texto, ahora)
    elif intencion == "confirmar_si":
        a["esperando_confirmacion"] = False
        a["confirmacion_tecnico"] = "si"
        r = "Gracias por confirmar. Quedó registrado que el servicio de la solicitud %s está en orden." % i
    elif intencion == "confirmar_no":
        a["esperando_confirmacion"] = False
        a["confirmacion_tecnico"] = "no"
        _para_pem(a, texto, ahora)
        r = ("Entendido. Le pasé tu mensaje al ingeniero de la solicitud %s; te respondo por aquí apenas me "
             "conteste." % i)
    else:
        _para_pem(a, texto, ahora)
        r = "Le pasé tu mensaje al ingeniero de la solicitud %s. Te respondo por aquí apenas me conteste." % i
    _anotar(a, "agente", r, ahora, intencion=intencion)
    return [(tel, r)]


def _para_pem(a, texto, ahora):
    a.setdefault("para_pem", []).append({"texto": texto, "hora": _iso(ahora)})
