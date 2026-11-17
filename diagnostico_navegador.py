# -*- coding: utf-8 -*-
"""Diagnostico: python diagnostico_navegador.py   -> muestra por que Chrome no abre."""
import os, sys, subprocess, tempfile, shutil
AQUI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, AQUI)
print("Python:", sys.version.split()[0])
try:
    import selenium; print("Selenium:", selenium.__version__)
except Exception as e:
    print("Selenium NO instalado:", e)
print("TEMP:", tempfile.gettempdir())
try:
    t = tempfile.mkdtemp(); shutil.rmtree(t); print("TEMP escribible: si")
except Exception as e:
    print("TEMP escribible: NO ->", e)
for ruta in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
    if os.path.exists(ruta):
        print("Chrome:", ruta)
        try:
            print(subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Item '%s').VersionInfo.ProductVersion" % ruta],
                                 capture_output=True, text=True).stdout.strip())
        except Exception:
            pass
print("Procesos chrome/chromedriver abiertos:")
try:
    print(subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"], capture_output=True, text=True).stdout[-300:])
except Exception:
    pass
from selenium import webdriver
perfil = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "hac_zac", "perfil_diag")
for nombre, args in (("simple, sin perfil", []), ("con perfil propio", ["--user-data-dir=" + perfil, "--no-first-run"])):
    o = webdriver.ChromeOptions()
    for a in args:
        o.add_argument(a)
    print("\n== Prueba:", nombre)
    try:
        d = webdriver.Chrome(options=o)
        print("OK ->", d.capabilities.get("browserVersion"), "driver", d.capabilities.get("chrome", {}).get("chromedriverVersion", "")[:12])
        d.quit()
    except Exception as e:
        print("FALLO:\n", str(e)[:1500])
input("\nEnter para cerrar...")
