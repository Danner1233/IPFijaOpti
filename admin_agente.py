# -*- coding: utf-8 -*-
"""AGENTE ADMINISTRADOR: reparte las solicitudes libres de la lista de SharePoint entre los ingenieros ACTIVOS.

* Un ingeniero esta ocupado si tiene una solicitud 'Asignada' (el estado lo guarda SharePoint, no hace falta
  carpeta compartida). Solo se asigna a ingenieros activos y libres, empezando por el que lleva mas tiempo sin recibir.
* Se asigna escribiendo su nombre en PEM_ASIGNADO. Si otro la tomo mientras tanto, SharePoint lo rechaza (ETag).
* Cada ingeniero, en su PC, corre sp_lector.py / correo_lector.py y solo ve lo suyo.

Ingenieros (el nombre debe ser EXACTAMENTE el de PEM_ASIGNADO):
    python admin_agente.py --agregar "Luis Paredes"
    python admin_agente.py --activar "Luis Paredes"      /  --desactivar "Luis Paredes"
    python admin_agente.py --lista
Repartir:
    python admin_agente.py --ver --simular      (primera vez: solo muestra a quien asignaria)
    python admin_agente.py                      (reparte cada 20 s)
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

_LOG = _log.obtener('admin_agente')  # noqa: E402


def ocupados(items):
    """Nombres (en minusculas, sin acentos) con una solicitud abierta (Est_Seg = Asignada) en la lista."""
    out = set()
    for it in items:
        d = cola.desde_sp(it)
        if cola._plano(d.get("est_seg")) == "asignada" and str(d.get("pem") or "").strip():
            out.add(cola._plano(d["pem"]))
    return out


def plan(items, ingenieros):
    """Lista de (item, ingeniero) a asignar ahora: la solicitud libre mas antigua a cada ingeniero activo y libre."""
    busy = ocupados(items)
    libres = sorted((it for it in items if cola.elegir_libre([it])), key=lambda i: str(i.get("Created") or ""))
    candidatos = [i for i in ingenieros if i.get("activo") and cola._plano(i["nombre"]) not in busy]
    candidatos.sort(key=lambda i: i.get("ultimo") or "")        # el que lleva mas tiempo sin recibir
    return list(zip(libres, candidatos))


def repartir(items, driver=None, simular=False):
    from sp_lector import asignar_item
    hechas = []
    roster = cola.ingenieros()
    for it, ing in plan(items, roster):
        if simular or driver is None:
            print("   [simulacion] solicitud", it["ID"], "->", ing["nombre"])
            continue
        if asignar_item(driver, it, ing["nombre"]):
            for r in roster:
                if r["nombre"] == ing["nombre"]:
                    r["ultimo"] = cola._ahora()
            hechas.append((it["ID"], ing["nombre"]))
    if hechas:
        cola.guardar_ingenieros(roster)
    return hechas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agregar"), ap.add_argument("--activar"), ap.add_argument("--desactivar")
    ap.add_argument("--lista", action="store_true")
    ap.add_argument("--ver", action="store_true"), ap.add_argument("--simular", action="store_true")
    ap.add_argument("--una", action="store_true"), ap.add_argument("--cada", type=int, default=20)
    ap.add_argument("--archivo", help="items.json de prueba (sin navegador)")
    a = ap.parse_args()

    if a.agregar:
        cola.agregar_ingeniero(a.agregar)
    if a.activar:
        cola.poner_activo(a.activar, True)
    if a.desactivar:
        cola.poner_activo(a.desactivar, False)
    if a.agregar or a.activar or a.desactivar or a.lista:
        for i in cola.ingenieros():
            print(("[ACTIVO]  " if i.get("activo") else "[inactivo]"), i["nombre"])
        return
    if a.archivo:
        with open(a.archivo, encoding="utf-8") as f:
            repartir(json.load(f), simular=True)
        return

    import sp_lector
    d = sp_lector.abrir(a.ver)
    if a.ver:
        input("Inicie sesion en SharePoint (debe verse la lista) y pulse Enter aqui...")
    try:
        while True:
            try:
                items = sp_lector.leer_items(d)
                hechas = repartir(items, d, a.simular)
                print(time.strftime("%H:%M:%S"), "asignadas:", hechas)
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "error:", e)
                _LOG.exception("error en el ciclo del lector")
            if a.una:
                break
            try:
                d.refresh()
            except Exception:
                pass
            time.sleep(a.cada)
    finally:
        d.quit()


if __name__ == "__main__":
    main()
