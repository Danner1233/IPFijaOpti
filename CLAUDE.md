# Contexto del proyecto: IP Fija Optimizacion

Usuario: Danner (Bogotá, Colombia). Escribe en español; responde siempre en español, claro y directo.
Trabaja en Puesta en Marcha (aprovisionamiento FTTx/GPON) para Claro Colombia. Es tecnólogo en desarrollo de software.
Sistema: Windows. Python 3 (py3) para la interfaz y los lectores; SecureCRT Portable ejecuta el script con Python 2.7 embebido.

## Qué hace la aplicación
Automatiza el aprovisionamiento de **IP fija FTTx** (solicitudes HAC/ZAC):
1. Una solicitud llega a una lista de **SharePoint** ("Asignar PEM": Seguimiento Expertos y Estándar - Solicitud IP Fija FTTx Campo).
2. El técnico se **autoasigna** la solicitud. Una cuenta **RR** (solo dígitos) identifica el caso.
3. Llega un **correo en Outlook** con la plantilla de la solicitud (SOLICITUD ID, MAC o serial, etc.).
4. El **script de SecureCRT** configura equipos (jump host, OLT/capa 2, capa 3) y la **GUI** (tkinter) maneja cola, historial, ajustes y centro de control.
5. Se documenta en Forms/portal (Playwright) y se escribe **Est_Seg** en SharePoint: Exitosa / No exitosa / Escalamiento.
   Solo se autoasigna otra solicitud cuando todas las propias están en esos estados.

## Estructura
- `SCRIPT_HAC_ZAC_UNIFICADO.py`: script de SecureCRT (py2.7). Recibe los datos por archivos JSON en la carpeta de datos.
- `hac_zac_gui.py` + `hac_zac/`: interfaz (pestañas Operación, Cola, Historial, IP Capa 2, Admin, Ajustes) y núcleo.
  - `cola.py` (cola.json con bloqueo entre procesos, estados `asignada/en_proceso/por_documentar/terminada`, pedidos de Est_Seg a SP), `servicio.py`, `plantilla.py`, `sesion.py` (latido de la ventana y `caso_entrante.json`), `forms_bot.py` (Playwright), `panel*.py`, `adaptable.py` (escala/DPI y scroll), `credenciales.py`, `log.py` (hac_zac.log rotativo).
- `servidor_central.py` + `hac_zac/reparto.py` (lógica pura) + `hac_zac/central_cliente.py` (latido de la app del PEM cada 15 s):
  reparto central por HTTP con token por PEM; el central tiene la única sesión de SharePoint. Fase 1 del sistema central.
- Fase 3: `hac_zac/agente.py` (lógica pura, barreras en código; la IA solo clasifica), `hac_zac/whatsapp.py` (Cloud API,
  firma X-Hub-Signature-256, transporte Consola), `hac_zac/ia.py` (Azure OpenAI por REST; token de `az` o api key),
  `chat_tecnico.py` (simulador). Rutas del central: /latido, /mensaje (PEM→técnico literal), /whatsapp (webhook).
- `hac_zac/presencia.py` (en línea/ausente/desconectado por carpeta compartida de OneDrive, `carpeta_equipo`),
  `hac_zac/tiempos.py` (límite Claro 15 / neutras 30 min desde la asignación; justificación obligatoria al documentar:
  fotos o observación o "Demora por parte del PEM"; `DialogoDemora` en panel.py), pestaña Equipo (`PanelEquipo`).
- Instalador: `armar_instalador.py` (zip con programa + copia del Python 3.15 local sin pip/pruebas) e
  `instalar.py` (lo corre INSTALAR.bat; no pisa datos del usuario; detecta SecureCRT/sesión por IP del jump host).
  `iniciar_hac_zac.py`/`INICIAR_HAC_ZAC.bat`: SecureCRT /S sesión /SCRIPT (con Portable llama al SecureCRT interno /F Data\Config).
- Estados/causas: `hac_zac/causas.py` (tabla No exitosa/Escalamiento por red), `estados.a_sp` ("No Exitosa",
  "Sin Asignar"), `DialogoResultado` en panel.py, `sp_lector.cambios_estado`/`JS_ESTADO` (Est_Seg + causa + nota
  agregada a Observaciones), `JS_LIBERAR` + `cola.pedir_liberar` (Sin Asignar, no se retoma 3 h).
- Reparto del admin: `hac_zac/reparto_equipo.py` (lógica pura + reparto.json + PIN), `sp_lector.repartir_equipo`
  (en cada vuelta si ajustes rol_admin + admin_repartir; admin_simular por defecto True), `PanelAdmin` (pestaña solo con
  rol_admin). Liberar deja nota "PEM X: liberó la solicitud" en Observaciones. `admin_agente.py` quedó obsoleto.
- `sp_lector.py`: lee la lista de SharePoint con Selenium y escribe estados (REST/ETag).
- `correo_lector.py`: busca en Outlook web la cuenta RR, abre los correos y confirma el SOLICITUD ID exacto antes de guardar la plantilla. Cada 15 s con pendientes, si no cada 60 s (`espera_siguiente`).
- `portal_csr.py`: consulta del Support Portal por serial o MAC.
- `navegador.py`: abre Chrome con perfil persistente en `%LOCALAPPDATA%\hac_zac\`; mostrar u ocultar ventana moviéndola fuera de pantalla (no headless).
- `ms_login.py` / `ms_numero.py`: inicio de sesión automático de Microsoft y ventana con el número de MFA.
- `hac_zac_dpapi.py`: cifrado DPAPI de las claves de `credenciales.json` (py2.7 y py3, sin dependencias).
- `tests/`: 51 pruebas (`py -3 -m unittest discover -s tests`; pytest no está instalado).

## Reglas de trabajo
- No usar OneDrive para perfiles de Chrome (rompe el arranque); por eso están en `%LOCALAPPDATA%`.
- Las credenciales se escriben en Ajustes (se guardan cifradas con DPAPI) y nunca en el código ni en el repositorio;
  `tests/test_seguridad.py` falla si el script trae una clave. Los datos de trabajo (`historial_capa2.json`, cola, ajustes,
  credenciales, registros) están en `.gitignore`.
- Python 3.15 con Tk 9: no mezclar `pack` y `grid` en el mismo contenedor.
- No hay SecureCRT, Chrome, SharePoint ni Outlook reales en el entorno de pruebas de Claude: lo que dependa de ellos se prueba con simulaciones y el usuario lo verifica en su PC. Dilo con claridad al entregar.
- Antes de cambiar la GUI, mantener la compatibilidad con pantallas y escalas distintas (`adaptable.py`).
- Correr las pruebas antes de entregar. Cambios en una rama `claude/...`, no directo en `master`.

## Estado actual (2026-11-17)
- Historial de Git reiniciado (tenía credenciales y datos de red); el repo debe quedar privado y las claves viejas cambiadas.
- Ventana cortada al abrir: causa real en `adaptable.py` (Scrollable no se enteraba del contenido que crecía). Arreglado; falta confirmar en el PC.
- Sin verificar en sistemas reales: selectores de Outlook, columnas de escritura en SharePoint, arranque de Chrome, descifrado DPAPI dentro de SecureCRT.
  Outlook: `py -3 correo_lector.py --una --debug` genera `outlook_debug_diagnostico.txt` (sin datos de clientes) y otros archivos de depuración.
- Fases 1 (reparto central) y 2 (correo central: `hilo_correo` en servidor_central.py reutiliza `correo_lector.revisar` con
  `pendientes`/`guardar` propios; el latido entrega `_correo`) hechas; falta probar con SharePoint/Outlook reales. Fase 3 (agente WhatsApp) hecha en simulación; falta app de Meta + ngrok y la IA real.
- Pendiente: Microsoft Graph para SharePoint/Outlook (requiere app en Entra ID por TI), partir el script de SecureCRT en módulos probables.

- Azure CLI del PC está dañado (`No module named 'knack.cli'`): reinstalar o usar api_key en ia.json.

## Proyecto aparte: agente de técnicos (`agente_tecnicos.zip`, no está en este repositorio)
Agente de IA que responde a técnicos (y luego por WhatsApp): lee el estado de la solicitud en SharePoint (asignada, exitosa, no exitosa, escalamiento).
- Rol **técnico**: recibe información de su caso.
- Rol **PEM**: da la observación (no exitosa/escalamiento) y el direccionamiento/IP final; el agente luego pregunta al técnico si todo quedó en orden.
- Azure del usuario: Foundry `foundry-danner`, proyecto `proj-default`, despliegue `gpt-5-mini`, autenticación con Entra ID (`az login`, rol Cognitive Services OpenAI User o Azure AI User).
- Barreras en código, no en el modelo: datos limitados por teléfono, direccionamiento literal, no inventar IPs.
- Pendiente: que `probar_ia` funcione con Azure, conectar el SharePoint real (Graph o Power Automate), WhatsApp Business API, alojarlo en Azure.
