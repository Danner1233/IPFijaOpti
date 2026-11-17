@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Servidor central HAC/ZAC
:menu
cls
echo ==========================================================
echo   SERVIDOR CENTRAL HAC/ZAC  (deje esta ventana ABIERTA)
echo ==========================================================
echo.
echo   1. Abrir en SIMULACION (no escribe en SharePoint)
echo   2. Abrir de VERDAD (reparte y escribe en SharePoint)
echo   3. Ver los PEM registrados
echo   4. Agregar un PEM (muestra su token)
echo   5. Token nuevo para un PEM
echo   6. Simulacion sin SharePoint + WhatsApp simulado (pruebas)
echo   7. Configurar IA (gpt-5-mini en Azure)
echo   8. Probar la IA
echo   9. Configurar WhatsApp (Meta)
echo   0. Salir
echo.
set /p op=Elija una opcion y pulse Enter:
if "%op%"=="1" goto simular
if "%op%"=="2" goto real
if "%op%"=="3" goto lista
if "%op%"=="4" goto agregar
if "%op%"=="5" goto token
if "%op%"=="6" goto demo
if "%op%"=="7" goto ia
if "%op%"=="8" goto probaria
if "%op%"=="9" goto whatsapp
if "%op%"=="0" exit /b
goto menu

:simular
py -3 servidor_central.py --simular --ver
pause
goto menu

:real
echo.
echo Va a repartir DE VERDAD (escribe PEM_ASIGNADO en SharePoint).
set /p ok=Escriba SI para continuar:
if /i not "%ok%"=="SI" goto menu
py -3 servidor_central.py --ver
pause
goto menu

:lista
py -3 servidor_central.py --lista
pause
goto menu

:agregar
set /p nom=Nombre EXACTO como aparece en PEM_ASIGNADO:
py -3 servidor_central.py --agregar "%nom%"
echo.
echo Copie el token (seleccione con el mouse y pulse Enter) y peguelo en la app: Ajustes ^> Reparto central.
pause
goto menu

:token
set /p nom=Nombre del PEM:
py -3 servidor_central.py --token "%nom%"
echo.
echo Copie el token (seleccione con el mouse y pulse Enter) y peguelo en la app: Ajustes ^> Reparto central.
pause
goto menu

:ia
echo.
echo Datos en el portal de Azure: su recurso de Foundry ^> "Claves y punto de conexion".
echo La clave no se ve al escribirla (se guarda cifrada en este PC).
py -3 servidor_central.py --configurar-ia
echo.
echo Si el central esta abierto, cierrelo (Ctrl+C) y abralo de nuevo para que use la IA.
pause
goto menu

:probaria
set /p frase=Escriba un mensaje como si fuera el tecnico:
py -3 servidor_central.py --probar-ia "%frase%"
pause
goto menu

:whatsapp
py -3 servidor_central.py --configurar-whatsapp
pause
goto menu

:demo
if not exist items_demo.json (
  echo [{"ID": 901, "Created": "2026-11-17T12:00:00Z", "PEM_ASIGNADO": "", "Est_Seg": "", "field_1": "64192718", "field_2": "CLIENTE PRUEBA", "ActivApoyo": "", "field_15": "TECNICO PRUEBA", "field_16": "3001234567"}] > items_demo.json
)
echo En otra ventana puede hacerse pasar por el tecnico:  py -3 chat_tecnico.py --tel 3001234567
py -3 servidor_central.py --archivo items_demo.json --demo --whatsapp-simulado
pause
goto menu
