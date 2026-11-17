# -*- coding: utf-8 -*-
"""Abre TODO con un clic: SecureCRT con la sesion del jump host + el script HAC/ZAC (que abre la ventana de la app).

    SecureCRT /S "<sesion>" /SCRIPT SCRIPT_HAC_ZAC_UNIFICADO.py

Datos (Ajustes, avanzado): ruta de SecureCRT (securecrt_exe) y sesion del jump host (sesion_crt).
Sin sesion configurada, SecureCRT abre solo con el script: elija la sesion y el script espera a que conecte.
Si la ventana del script ya esta abierta, no se abre otra.
"""
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
SCRIPT = os.path.join(AQUI, "SCRIPT_HAC_ZAC_UNIFICADO.py")


def ajustes():
    try:
        from hac_zac.servicio import cargar_ajustes
        return cargar_ajustes()
    except Exception:
        try:
            with open(os.path.join(AQUI, "ajustes.json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def resolver_portable(exe):
    """Para SecureCRTPortable.exe: (SecureCRT.exe interno, carpeta Data\\Config). Si no es portable: (None, None)."""
    if os.path.basename(exe).lower() != "securecrtportable.exe":
        return None, None
    base = os.path.dirname(exe)
    config = os.path.join(base, "Data", "Config")
    for sub in ("ProgramFiles64", "ProgramFiles", ""):
        real = os.path.join(base, "App", sub, "SecureCRT.exe")
        if os.path.isfile(real):
            return real, config
    return None, None


def comando(aj):
    """Lista para subprocess, o ValueError con un mensaje claro."""
    exe = str(aj.get("securecrt_exe") or "").strip().strip('"')
    if not exe:
        raise ValueError("Falta la ruta de SecureCRT. Escribala en la aplicacion: Ajustes > Mostrar funciones "
                         "avanzadas > Ruta de SecureCRT.")
    if not os.path.isfile(exe):
        raise ValueError("No existe SecureCRT en:\n%s\n\nCorrija la ruta en Ajustes." % exe)
    if not os.path.isfile(SCRIPT):
        raise ValueError("No encuentro el script:\n%s" % SCRIPT)
    cmd = [exe]
    real, config = resolver_portable(exe)
    if real:
        # SecureCRTPortable.exe NO pasa /S ni /SCRIPT: se llama al SecureCRT interno con la configuracion del portable
        cmd = [real, "/F", config]
    sesion = str(aj.get("sesion_crt") or "").strip()
    if sesion:
        cmd += ["/S", sesion]
    return cmd + ["/SCRIPT", SCRIPT]


def ya_abierta():
    try:
        from hac_zac import sesion
        return sesion.hay_ventana_viva()
    except Exception:
        return False


def avisar(texto, error=False):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)("HAC / ZAC", texto)
        r.destroy()
    except Exception:
        print(texto)


def main():
    if ya_abierta():
        avisar("La ventana de HAC / ZAC ya esta abierta (con su SecureCRT). Use esa.")
        return 0
    try:
        cmd = comando(ajustes())
    except ValueError as e:
        avisar(str(e), error=True)
        return 1
    subprocess.Popen(cmd, cwd=os.path.dirname(cmd[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
