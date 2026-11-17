# -*- coding: utf-8 -*-
"""Arma el paquete de instalacion de HAC ZAC (lo corre el administrador en SU PC):

    py -3 armar_instalador.py --salida "<carpeta del equipo en OneDrive>\\HAC_ZAC instalador"

Deja dos archivos:  INSTALAR.bat  +  HAC_ZAC.zip  (programa + Python con todo lo necesario + base de Capa 2).
Cada PEM: doble clic en INSTALAR.bat. Para actualizar a todos: volver a armar y que cada uno lo ejecute de nuevo
(sus ajustes, claves e historial se conservan).
"""
import argparse
import os
import subprocess
import sys
import time
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))

# Lo que NO hace falta del Python (pesa y no se usa)
EXCLUIR_PY_DIRS = {"__pycache__", "test", "tests", "idlelib", "turtledemo", "Doc", "Tools", "include", "libs",
                   "pip", "setuptools", "PyInstaller", "_pyinstaller_hooks_contrib", "openpyxl", "et_xmlfile",
                   "pyinstaller", "altgraph", "pefile", "pywin32-ctypes"}
EXCLUIR_PY_PREFIJOS = ("pip-", "setuptools-", "pyinstaller", "openpyxl-", "et_xmlfile-", "altgraph-", "pefile-")
EXCLUIR_PY_EXT = (".pdb", ".pyc")

INSTALAR_BAT = r"""@echo off
chcp 65001 >nul
title Instalando HAC ZAC
echo.
echo   Instalando HAC ZAC... (puede tardar 1 o 2 minutos, no cierre esta ventana)
echo.
set "STAGE=%TEMP%\hac_zac_instalacion"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0HAC_ZAC.zip' -DestinationPath '%STAGE%' -Force"
if errorlevel 1 (
  echo No se pudo descomprimir HAC_ZAC.zip. Verifique que OneDrive termino de descargarlo.
  pause
  exit /b 1
)
"%STAGE%\programa\python\python.exe" "%STAGE%\programa\instalar.py" --origen "%STAGE%\programa" --destino "%LOCALAPPDATA%\HAC_ZAC" --equipo "%~dp0.."
set "R=%errorlevel%"
rmdir /s /q "%STAGE%" >nul 2>nul
if not "%R%"=="0" pause
exit /b %R%
"""


def archivos_programa():
    """Archivos versionados en Git (sin pruebas ni herramientas internas)."""
    salida = subprocess.run(["git", "ls-files"], cwd=AQUI, capture_output=True, text=True, check=True).stdout
    fuera = ("tests/", ".gitignore", "armar_instalador.py")
    return [f for f in salida.splitlines() if f and not f.startswith(fuera)]


def archivos_python(base):
    """(ruta absoluta, ruta dentro del zip) del Python a incluir."""
    for raiz, dirs, archivos in os.walk(base):
        dirs[:] = [d for d in dirs if d not in EXCLUIR_PY_DIRS and not d.lower().startswith(EXCLUIR_PY_PREFIJOS)]
        for a in archivos:
            if a.endswith(EXCLUIR_PY_EXT):
                continue
            ruta = os.path.join(raiz, a)
            yield ruta, os.path.join("programa", "python", os.path.relpath(ruta, base))


def version():
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=AQUI, capture_output=True, text=True).stdout
    except Exception:
        h = ""
    return "%s %s" % (time.strftime("%Y-%m-%d %H:%M"), h.strip())


def armar(salida, con_historial=True, python_base=None, log=print):
    python_base = python_base or sys.base_prefix
    for mod in ("tkinter", "selenium", "playwright"):
        __import__(mod)                             # que el Python a incluir tenga lo necesario
    os.makedirs(salida, exist_ok=True)
    zip_ruta = os.path.join(salida, "HAC_ZAC.zip")
    tmp = zip_ruta + ".tmp"
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in archivos_programa():
            z.write(os.path.join(AQUI, f), os.path.join("programa", f))
            n += 1
        if con_historial and os.path.isfile(os.path.join(AQUI, "historial_capa2.json")):
            z.write(os.path.join(AQUI, "historial_capa2.json"), os.path.join("programa", "historial_capa2.json"))
            n += 1
        z.writestr(os.path.join("programa", "VERSION"), version())
        for ruta, dentro in archivos_python(python_base):
            z.write(ruta, dentro)
            n += 1
    os.replace(tmp, zip_ruta)
    with open(os.path.join(salida, "INSTALAR.bat"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(INSTALAR_BAT)
    mb = os.path.getsize(zip_ruta) / 1e6
    log("Listo: %s\n  HAC_ZAC.zip: %d archivos, %.0f MB\n  INSTALAR.bat" % (salida, n, mb))
    return zip_ruta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=os.path.join(AQUI, "dist", "HAC_ZAC instalador"))
    ap.add_argument("--sin-historial", action="store_true", help="no incluir historial_capa2.json")
    a = ap.parse_args()
    armar(a.salida, not a.sin_historial)


if __name__ == "__main__":
    main()
