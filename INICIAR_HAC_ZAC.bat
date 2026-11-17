@echo off
rem Abre SecureCRT con la sesion del jump host y el script HAC/ZAC (que abre la ventana de la app).
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0iniciar_hac_zac.py") || (start "" pythonw "%~dp0iniciar_hac_zac.py")
