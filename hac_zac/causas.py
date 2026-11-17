# -*- coding: utf-8 -*-
"""Causas de NO EXITOSA y ESCALAMIENTO (tabla del proceso), con responsable de notificar/escalar y la accion.

El texto de "causa" se escribe tal cual en SharePoint (columnas "Causa No Exitosa" / "Causa Escalamiento").
Cada causa se muestra solo para su red: las que empiezan por ATP / ONNET / Claro / Red Propia son de esa red;
las demas son generales (sirven para cualquier red).
"""
from . import estados

# (causa, responsable de notificar, responsable de escalar, accion / notificacion)
_ESCALAMIENTO = (
    ("ATP ID Reserva Creado SIN IP", "PEM", "PEM", "Cambio de ID de Reserva en Portal de Aprovisionamiento FTTx"),
    ("ATP ONT No Sincronizada", "PEM", "Técnico",
     "Asegurar la conectividad de la ONT (Capa física) y ejecutar el proceso de activación del servicio desde WFM"),
    ("Escalado por solicitud de Direccionamiento", "PEM", "PEM",
     "Realizar la documentación establecida en el SP de solicitudes para que el automatismo genere el reporte, cree "
     "el correo y sea enviado y, cargue la solicitud de manera redundante por el grupo de Teams que se tiene con el "
     "personal de CORE"),
    ("Falla Acceso Emanagement", "PEM", "PEM", "Generar escalamiento a líderes técnicos de Claro"),
    ("Falla Acceso Netcracker", "PEM", "PEM", "Generar escalamiento a líderes técnicos de Claro"),
    ("Falla Acceso por CLI (Hendryx-Taccacs)", "PEM", "PEM", "Generar escalamiento a líderes técnicos de Claro"),
    ("Falla Gestor Acceso NCE (Huawei)", "PEM", "PEM", "Generar escalamiento a líderes técnicos de Claro"),
    ("Falla Gestor Acceso Netnumen (ZTE)", "PEM", "PEM", "Generar escalamiento a líderes técnicos de Claro"),
    ("Falla Gestor ACS Friendly", "PEM", "PEM", "Generar escalamiento a líderes técnicos de Claro"),
    ("Red Propia ONT No Sincronizada", "PEM", "Técnico",
     "Asegurar la conectividad de la ONT (Capa física) y ejecutar el proceso de activación del servicio desde WFM"),
    ("ONNET Requiere caso TCO / Bridge", "PEM", "PEM",
     "Creación de TCO en la plataforma de ServiceNow, donde se solicite la configuración de bridge"),
    ("ONNET ONT No Sincronizada", "PEM", "Técnico",
     "Asegurar la conectividad de la ONT (Capa física) y ejecutar el proceso de activación del servicio desde WFM"),
    ("ATP Requiere caso INCLA / Bridge", "PEM", "PEM",
     "Creación de INCLA en la plataforma de JIRA, donde se solicite la configuración de bridge"),
)

_NO_EXITOSA = (
    ("ATP Falla Posterior a 24Hrs", "PEM", "Técnico",
     "Solicitar soporte de NOC, entrega de IP asignada supera las 24Hrs"),
    ("ATP No Responde a PING", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que garantice que solo haya un ID de reserva y un solo ID de Serivicio "
     "creado para esta cuenta y que también garantice que NO hay un cruce de hilos"),
    ("ATP ID Reserva No Existe", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que le sea indicado cual es el ID de Reserva correcto y que garantice que "
     "solo haya un ID de reserva y un solo ID de Serivicio creado para esta cuenta"),
    ("ATP Sin puertos disponibles en CTO", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que creen un INCLA por el cual se realice la ampliación de puertos"),
    ("Cliente Cancela IP Fija", "PEM", "",
     "Solicitar soporte de servicio/CCOT para que sea retirado el código de IP Fija y le sea actualizada la orden de "
     "WFM"),
    ("Cliente no puede esperar", "PEM", "Técnico", "Reportar a supervisor para definir si se razona"),
    ("Tarifa B.A. FTTX sin IP Fija", "PEM", "Técnico",
     "Lanzar activación de servicio y hacer entrega a cliente, ya que el servicio NO va con IP"),
    ("ONNET Falla Posterior a 24Hrs", "PEM", "Técnico",
     "Solicitar soporte de NOC, entrega de IP asignada supera las 24Hrs"),
    ("ONNET Cambio Vías", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que ejecuten el ajuste de vías tal como el técnico requiere"),
    ("ONNET ID Servicio en Pending Active", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que garantice que solo haya un ID de reserva y un solo ID de Serivicio "
     "creado para esta cuenta"),
    ("ONNET ID Servicio Cancelado", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que garantice que solo haya un ID de reserva y un solo ID de Serivicio "
     "creado para esta cuenta y en caso de generar uno nuevo, que garanticen las misma vías actuales y que hagan el "
     "alta del servicio"),
    ("ONNET No Responde a PING", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que garantice que solo haya un ID de reserva y un solo ID de Serivicio "
     "creado para esta cuenta, que también garantice que NO hay un cruce de hilos"),
    ("ONNET ID Reserva No Existe", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que le sea indicado cual es el ID de Reserva correcto y que garantice que "
     "solo haya un ID de reserva y un solo ID de Serivicio creado para esta cuenta"),
    ("ONNET Requiere Cambio Id Reserva", "PEM", "Técnico",
     "Solicitar soporte de Suportlink para que garantice la creación de un ID de reserva y que las vías correspondan "
     "a las requeridas por el técnico"),
    ("Claro Falla Posterior a 24Hrs", "PEM", "Técnico",
     "Solicitar soporte de NOC, entrega de IP asignada supera las 24Hrs"),
    ("Solicitud con Inconsistencia en Datos", "PEM", "Técnico",
     "Debe revisar y asegurar que la información que carga en la solicitud, corresponda fielmente a la actividad en "
     "ejecución"),
    ("Solicitud Duplicada", "PEM", "Técnico",
     "Esta actividad quedará marcada con esta tipificación y se atendera con la primera solicitud cargada."),
    ("Solicitud Realizada en Domingo/Festivo sin Notificación Previa", "PEM", "Técnico",
     "Las agendas para días dominicales o festivos deben ser socializadas con al menos un día hábil de anterioridad "
     "(incluyendo el sábado como día hábil), si no se realizó, se marcará como NO EXITOSA"),
)

# Columna de SharePoint donde va la causa de cada estado
COLUMNA = {estados.NO_EXITOSA: "Causa_x0020_No_x0020_Exitosa", estados.ESCALAMIENTO: "Causa_x0020_Escalamiento"}


def red_de_causa(causa):
    c = causa.upper()
    if c.startswith("ATP "):
        return "ATP"
    if c.startswith("ONNET "):
        return "ONNET"
    if c.startswith(("CLARO ", "RED PROPIA ")):
        return "CLARO"
    return ""                                     # general: cualquier red


def _tabla(estado):
    return {estados.NO_EXITOSA: _NO_EXITOSA, estados.ESCALAMIENTO: _ESCALAMIENTO}.get(estado, ())


def para(estado, red=""):
    """Causas que aplican: las de esa red + las generales (sin red: todas). [dict]"""
    out = []
    for causa, notifica, escala, accion in _tabla(estado):
        r = red_de_causa(causa)
        if not red or not r or r == red:
            out.append({"causa": causa, "notifica": notifica, "escala": escala, "accion": accion, "red": r})
    return out


def buscar(estado, causa):
    return next((c for c in para(estado) if c["causa"] == causa), None)


def requiere_causa(estado):
    return estado in COLUMNA
