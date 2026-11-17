# -*- coding: utf-8 -*-
"""Ventanita con el numero de verificacion de Microsoft. Se cierra sola cuando se borra el archivo o a los 3 min."""
import os
import sys
import json
import time
import tkinter as tk


def main():
    ruta = sys.argv[1]
    try:
        numero = json.load(open(ruta, encoding="utf-8")).get("numero", "")
    except Exception:
        return
    r = tk.Tk()
    r.title("Verificacion de Microsoft")
    r.attributes("-topmost", True)
    r.configure(bg="#10131a")
    r.geometry("+60+60")
    tk.Label(r, text="Apruebe en su celular este número", bg="#10131a", fg="#cfd6e4", font=("Segoe UI", 12)).pack(padx=30, pady=(18, 0))
    tk.Label(r, text=numero, bg="#10131a", fg="#ffffff", font=("Segoe UI", 54, "bold")).pack(padx=30, pady=(0, 18))
    fin = time.time() + 180

    def vigilar():
        if not os.path.exists(ruta) or time.time() > fin:
            r.destroy()
            return
        r.after(1000, vigilar)

    vigilar()
    r.mainloop()


if __name__ == "__main__":
    main()
