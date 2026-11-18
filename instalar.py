# -*- coding: utf-8 -*-
"""Instala (o actualiza) HAC ZAC en este PC. Lo ejecuta INSTALAR.bat con el Python que trae el paquete.

* Copia el programa a %LOCALAPPDATA%\\HAC_ZAC (fuera de OneDrive). Al ACTUALIZAR no toca los datos del usuario
  (ajustes, claves, cola, historial, fotos de demoras).
* Busca SecureCRT (instalado o portable) y la sesion del jump host (por su IP).
* Deja configurada la carpeta del equipo (donde esta el instalador) y crea el acceso directo "HAC ZAC".
* Al final abre HAC ZAC.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

JUMP_HOST = "172.31.238.6"
# Archivos y carpetas del USUARIO: si ya existen en el destino, nunca se reemplazan.
DATOS_USUARIO = {"ajustes.json", "credenciales.json", "historial_capa2.json", "cola.json", "ingenieros.json",
                 "sp_pendientes.json", "registro_sharepoint.jsonl", "historial_documentacion.json",
                 "documentacion.json", "plantilla_base.txt", "correos_vistos.txt",
                 "pausa.json", "conexion.json", "reportes_pendientes.json"}
CARPETAS_USUARIO = {"solicitudes", "demoras", "browser_profile"}


# ---------------------------------------------------------------------------------------------- copia
def copiar_programa(origen, destino):
    """Copia todo de origen a destino sin pisar datos del usuario. Devuelve (copiados, conservados)."""
    copiados = conservados = 0
    for raiz, dirs, archivos in os.walk(origen):
        rel_dir = os.path.relpath(raiz, origen)
        if rel_dir == ".":
            dirs[:] = [d for d in dirs if not (d in CARPETAS_USUARIO and os.path.isdir(os.path.join(destino, d)))]
        os.makedirs(os.path.join(destino, rel_dir), exist_ok=True)
        for a in archivos:
            rel = os.path.normpath(os.path.join(rel_dir, a))
            dst = os.path.join(destino, rel)
            if rel in DATOS_USUARIO and os.path.exists(dst):
                conservados += 1
                continue
            shutil.copy2(os.path.join(raiz, a), dst)
            copiados += 1
    return copiados, conservados


# ---------------------------------------------------------------------------------------------- SecureCRT
def _candidatos_fijos():
    pf = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    for base in filter(None, pf):
        yield os.path.join(base, "VanDyke Software", "SecureCRT", "SecureCRT.exe")
        yield os.path.join(base, "VanDyke Software", "Clients", "SecureCRT.exe")


def buscar_securecrt(raices=None, profundidad=6):
    """El SecureCRT a usar. Si hay varios (instalado y/o copias portables), el que tiene la sesion del jump host
    con nombre; despues, el que tiene alguna sesion al jump host; despues, el usado mas recientemente."""
    candidatos = [c for c in _candidatos_fijos() if os.path.isfile(c)] + list(_portables(raices, profundidad))

    def puntaje(exe):
        carpeta = carpeta_sesiones(exe)
        s = buscar_sesion(carpeta)
        nivel = 2 if s and s.split("/")[-1] != JUMP_HOST else (1 if s else 0)
        try:
            usado = os.path.getmtime(carpeta)
        except OSError:
            usado = 0
        return nivel, usado
    return max(candidatos, key=puntaje) if candidatos else ""


def _portables(raices=None, profundidad=6):
    """Todas las copias de SecureCRTPortable.exe en Escritorio/Documentos/Descargas/OneDrive."""
    if raices is None:
        perfil = os.path.expanduser("~")
        raices = [os.path.join(perfil, d) for d in os.listdir(perfil)
                  if d.lower().startswith("onedrive")] + [os.path.join(perfil, d) for d in
                                                          ("Desktop", "Escritorio", "Documents", "Downloads")]
    saltar = {"appdata", "node_modules", ".git", "python", "__pycache__", "windows"}
    for raiz in raices:
        if not os.path.isdir(raiz):
            continue
        nivel0 = raiz.rstrip("\\/").count(os.sep)
        for r, dirs, archivos in os.walk(raiz):
            if r.count(os.sep) - nivel0 >= profundidad:
                dirs[:] = []
            dirs[:] = [d for d in dirs if d.lower() not in saltar]
            for a in archivos:
                if a.lower() == "securecrtportable.exe":
                    yield os.path.join(r, a)


def carpeta_sesiones(exe):
    if not exe:
        return ""
    if os.path.basename(exe).lower() == "securecrtportable.exe":
        return os.path.join(os.path.dirname(exe), "Data", "Config", "Sessions")
    return os.path.join(os.environ.get("APPDATA", ""), "VanDyke", "Config", "Sessions")


def buscar_sesion(carpeta, host=JUMP_HOST):
    """Nombre de la sesion guardada que apunta al jump host ('' si no hay)."""
    if not carpeta or not os.path.isdir(carpeta):
        return ""
    encontradas = []
    for r, _d, archivos in os.walk(carpeta):
        for a in archivos:
            if not a.lower().endswith(".ini") or a in ("__FolderData__.ini", "Default.ini"):
                continue
            try:
                with open(os.path.join(r, a), "rb") as f:
                    texto = f.read().decode("utf-8", "ignore")
            except OSError:
                continue
            if 'S:"Hostname"=%s' % host in texto:
                nombre = os.path.relpath(os.path.join(r, a[:-4]), carpeta).replace(os.sep, "/")
                encontradas.append(nombre)
    # preferir una sesion con nombre (ej. HENDRIX_DEMIMASTER) sobre una llamada como la IP
    encontradas.sort(key=lambda n: (n.split("/")[-1] == host, n.lower()))
    return encontradas[0] if encontradas else ""


# ---------------------------------------------------------------------------------------------- ajustes
def configurar(destino, carpeta_equipo, exe, sesion):
    """Completa ajustes.json SOLO en lo que esta vacio (no pisa lo que el usuario ya configuro)."""
    ruta = os.path.join(destino, "ajustes.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            aj = json.load(f)
    except (OSError, ValueError):
        aj = {}
    for k, v in (("securecrt_exe", exe), ("sesion_crt", sesion), ("carpeta_equipo", carpeta_equipo)):
        if v and not str(aj.get(k) or "").strip():
            aj[k] = v
    aj["auto_asignar"] = False                 # solo los administradores asignan
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(aj, f, ensure_ascii=False, indent=2)
    return aj


def acceso_directo(destino, nombre="HAC ZAC", carpeta=None):
    """Acceso directo en el escritorio (tambien si el escritorio esta en OneDrive). Devuelve la ruta o ''."""
    pythonw = os.path.join(destino, "python", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = os.path.join(destino, "python", "python.exe")
    donde = ("$d='%s';" % carpeta) if carpeta else "$d=[Environment]::GetFolderPath('Desktop');"
    ps = (donde + " $s=(New-Object -ComObject WScript.Shell).CreateShortcut("
          "(Join-Path $d '%s.lnk')); $s.TargetPath='%s'; $s.Arguments='\"%s\"'; $s.WorkingDirectory='%s'; "
          "$s.Description='Abre SecureCRT + script HAC ZAC'; $s.Save(); Join-Path $d '%s.lnk'") % (
        nombre, pythonw, os.path.join(destino, "iniciar_hac_zac.py"), destino, nombre)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def app_abierta(destino):
    try:
        with open(os.path.join(destino, "gui_activa.json"), encoding="utf-8") as f:
            import time
            return time.time() - float(json.load(f).get("t", 0)) <= 15
    except Exception:
        return False


def avisar(texto, error=False):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)("Instalar HAC ZAC", texto)
        r.destroy()
    except Exception:
        print(texto)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origen", required=True)
    ap.add_argument("--destino", required=True)
    ap.add_argument("--equipo", default="", help="carpeta compartida del equipo")
    ap.add_argument("--sin-abrir", action="store_true")
    ap.add_argument("--sin-acceso", action="store_true")
    ap.add_argument("--silencioso", action="store_true", help="sin ventanas de aviso (pruebas)")
    a = ap.parse_args()
    if os.environ.get("HAC_ZAC_INSTALAR_PRUEBA"):          # pruebas automaticas del INSTALAR.bat
        a.silencioso = a.sin_abrir = a.sin_acceso = True
    if a.silencioso:
        global avisar
        avisar = lambda texto, error=False: print(("ERROR: " if error else "") + texto)  # noqa: E731
    destino = os.path.abspath(a.destino)
    actualizacion = os.path.isfile(os.path.join(destino, "iniciar_hac_zac.py"))
    if app_abierta(destino):
        avisar("HAC ZAC está abierto. Ciérrelo (y su SecureCRT) y vuelva a ejecutar INSTALAR.", error=True)
        return 1
    try:
        copiados, conservados = copiar_programa(a.origen, destino)
    except PermissionError as e:
        avisar("No se pudo copiar (¿HAC ZAC sigue abierto?).\n\n%s" % e, error=True)
        return 1
    exe = buscar_securecrt()
    sesion = buscar_sesion(carpeta_sesiones(exe))
    equipo = os.path.abspath(a.equipo) if a.equipo and os.path.isdir(a.equipo) else ""
    aj = configurar(destino, equipo, exe, sesion)
    lnk = "" if a.sin_acceso else acceso_directo(destino)
    faltan = []
    if not aj.get("securecrt_exe"):
        faltan.append("• No encontré SecureCRT: escriba su ruta en Ajustes (funciones avanzadas).")
    if not aj.get("sesion_crt"):
        faltan.append("• No encontré la sesión del jump host %s en SecureCRT: escríbala en Ajustes." % JUMP_HOST)
    msg = ("HAC ZAC %s.\n\n" % ("actualizado" if actualizacion else "instalado") +
           ("Acceso directo en el escritorio: HAC ZAC\n" if lnk else "") +
           ("SecureCRT: %s\nSesión: %s\n" % (aj.get("securecrt_exe") or "—", aj.get("sesion_crt") or "—")) +
           ("\n" + "\n".join(faltan) + "\n" if faltan else "") +
           ("" if actualizacion else "\nPrimera vez: en Ajustes escriba su nombre (como en SharePoint) y sus claves."))
    avisar(msg)
    if not a.sin_abrir and aj.get("securecrt_exe"):
        pythonw = os.path.join(destino, "python", "pythonw.exe")
        subprocess.Popen([pythonw if os.path.isfile(pythonw) else sys.executable,
                          os.path.join(destino, "iniciar_hac_zac.py")], cwd=destino)
    print("copiados %d, conservados %d" % (copiados, conservados))
    return 0


if __name__ == "__main__":
    sys.exit(main())
