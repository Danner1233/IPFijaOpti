"""Procesos en segundo plano (lectores y agente administrador) controlados desde la interfaz."""
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # carpeta donde estan los scripts


class Proceso:
    """Un script de Python que corre en segundo plano; su salida va a una cola para mostrarla en pantalla."""

    def __init__(self, nombre, script):
        self.nombre, self.script = nombre, script
        self.p = None
        self.salida = queue.Queue()
        self.espera_enter = False

    def vivo(self):
        return self.p is not None and self.p.poll() is None

    def iniciar(self, args, ver=False):
        if self.vivo():
            return
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = 0x08000000 if os.name == "nt" else 0           # sin ventana negra
        self.p = subprocess.Popen(
            [sys.executable, "-u", str(RAIZ / self.script)] + list(args), cwd=str(RAIZ),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", env=env, creationflags=flags)
        self.espera_enter = bool(ver)
        self.salida.put("--- %s iniciado ---" % self.nombre)
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self):
        try:
            for linea in self.p.stdout:
                self.salida.put(linea.rstrip())
        except Exception:
            pass
        self.salida.put("--- %s detenido ---" % self.nombre)
        self.espera_enter = False

    def enter(self):
        """'Ya inicie sesion': el script esta esperando un Enter."""
        try:
            self.p.stdin.write("\n")
            self.p.stdin.flush()
            self.espera_enter = False
        except Exception:
            pass

    def detener(self):
        if not self.vivo():
            return
        if os.name == "nt":                                    # mata tambien Chrome y chromedriver
            subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"], capture_output=True,
                           creationflags=0x08000000)
        else:
            self.p.terminate()
