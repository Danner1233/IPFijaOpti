# -*- coding: utf-8 -*-
"""SIMULADOR del tecnico por WhatsApp (para probar el agente sin Meta).

1) Servidor central con WhatsApp simulado, por ejemplo sin SharePoint:
       py -3 servidor_central.py --archivo items.json --demo --whatsapp-simulado
2) En otra ventana, hagase pasar por el tecnico (su celular debe ser el de la solicitud):
       py -3 chat_tecnico.py --tel 3001234567
   Escriba como si fuera el tecnico; vera lo que el agente le contestaria por WhatsApp.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from hac_zac.agente import telefono  # noqa: E402
from servidor_central import carpeta_central  # noqa: E402


def enviar(url, tel, texto):
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": tel, "id": "sim-%d" % int(time.time() * 1000), "type": "text", "text": {"body": texto}}]}}]}]}
    req = urllib.request.Request(url + "/whatsapp", data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def seguir(rutas, tel, parar):
    """Muestra lo que el agente le envia a ese telefono (central real y carpeta de la demo)."""
    pos = {r: (os.path.getsize(r) if os.path.exists(r) else 0) for r in rutas}
    while not parar.is_set():
        for ruta in rutas:
            if not os.path.exists(ruta):
                continue
            if os.path.getsize(ruta) < pos[ruta]:
                pos[ruta] = 0                           # la demo arranco de nuevo (archivo nuevo)
            if os.path.getsize(ruta) > pos[ruta]:
                with open(ruta, encoding="utf-8") as f:
                    f.seek(pos[ruta])
                    for linea in f:
                        try:
                            m = json.loads(linea)
                        except ValueError:
                            continue
                        if m.get("a") == tel:
                            print("\n[AGENTE %s]\n%s\n" % (m["hora"][11:19], m["texto"]))
                    pos[ruta] = f.tell()
                print("tecnico> ", end="", flush=True)
        time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tel", required=True, help="celular del tecnico tal como esta en la solicitud")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    a = ap.parse_args()
    tel = telefono(a.tel)
    parar = threading.Event()
    base = carpeta_central().rstrip("\\/")
    rutas = [os.path.join(base, "whatsapp_salida.jsonl"), os.path.join(base + "_demo", "whatsapp_salida.jsonl")]
    threading.Thread(target=seguir, args=(rutas, tel, parar), daemon=True).start()
    print("Simulador del tecnico %s. Escriba y pulse Enter (Ctrl+C para salir)." % tel)
    try:
        while True:
            texto = input("tecnico> ").strip()
            if texto:
                try:
                    enviar(a.url, tel, texto)
                except Exception as e:
                    print("No pude enviar al servidor central (%s). ¿Lo inicio con --whatsapp-simulado?" % e)
    except (KeyboardInterrupt, EOFError):
        parar.set()


if __name__ == "__main__":
    main()
