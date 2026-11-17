# HAC/ZAC – Automatización de aprovisionamiento

## Estructura
- `SCRIPT_HAC_ZAC_UNIFICADO.py`  Script de SecureCRT (Python 2.7 embebido). Ejecuta HAC/ZAC y queda en bucle esperando solicitudes.
- `hac_zac_gui.py`  Interfaz (tkinter). Se comunica con el script por archivos JSON en la carpeta de datos.
- `sp_lector.py`  Lee la lista SharePoint "Asignar PEM" y se autoasigna solicitudes libres (PEM_ASIGNADO vacío).
- `correo_lector.py`  Lee el correo (Outlook web) y empareja con la solicitud por cuenta RR.
- `portal_csr.py`  Consulta del portal por serial/MAC.
- `admin_agente.py`  Agente de administración / cola.
- `navegador.py`, `diagnostico_navegador.py`  Lanzador robusto de Chrome y diagnóstico.
- `hac_zac/`  Núcleo: `plantilla`, `cola`, `servicio`, `forms_bot`, `panel*`, `adaptable`, `log`.
- `historial_capa2.json`  Base de datos de capa 2. Debe quedar junto a los programas. NO va en el repositorio (trae IPs de la red).
- `tests/`  Pruebas automáticas.

## Instalación
1. Descomprimir en una carpeta y copiar ahí su `historial_capa2.json` (no viene en el repositorio).
2. `pip install -r requirements.txt`
3. Abrir `CENTRO_DE_CONTROL.bat` o `hac_zac_gui.py` y escribir usuarios y claves en **Ajustes** (Support Portal, Microsoft, SecureCRT).
4. Cargar el script en SecureCRT.

## Flujo
SharePoint (solicitud sin PEM) → autoasignación → correo con la misma RR → portal (serial/MAC) → script → plantilla → Forms.
Al terminar, el script vuelve al jump host y queda listo para otro proceso.

## Una sola ventana
La ventana que abre el script de SecureCRT incluye la pestaña **Cola** y arranca los lectores (SharePoint y correo).
"Procesar" en la cola carga el caso en esa misma ventana: no abre otro script ni otro SecureCRT.
Si se usa `CENTRO_DE_CONTROL.bat`, "Procesar" le pasa el caso a la ventana del script que ya esté abierta.

## Asignación y estado en SharePoint
- Al **documentar** (Forms enviado), la solicitud queda en SharePoint como Exitosa / No exitosa / Escalamiento.
- Solo se toma otra solicitud libre cuando todas las mías están en uno de esos tres estados (o ya documentadas).
- Terminar el proceso en CRT NO libera: libera documentar.

## Correo y navegadores
- Cada minuto el lector actualiza Outlook y, por cada solicitud mía sin plantilla, busca su cuenta RR (solo dígitos),
  abre los correos que salen y carga solo el que trae el mismo SOLICITUD ID.
- En Cola, "Ver navegador" (SharePoint / Correo / Portal) muestra u oculta cada ventana sin cerrarla.
- Estados de la cola: asignada -> en proceso -> por documentar (al terminar CRT) -> terminada (solo al documentar).

## Reparto central (fase 1)
Un PC (luego Azure) reparte las solicitudes; los PEM ya no abren SharePoint.

**Administrador (PC central)**
1. Registrar a cada PEM con el nombre EXACTO de la columna PEM_ASIGNADO; muestra su token:
   `py -3 servidor_central.py --agregar "Nombre Apellido"`  (`--lista`, `--token "Nombre"` para cambiarlo, `--quitar`)
2. Primera vez, en simulación (inicia sesión en SharePoint y solo muestra a quién asignaría):
   `py -3 servidor_central.py --simular --ver`
3. De verdad: `py -3 servidor_central.py`. Windows preguntará por el Firewall: permitir en **redes privadas**.
   Datos del central: `%LOCALAPPDATA%\hac_zac\central` (aparte de los de la aplicación, aunque sea el mismo PC).

**Cada PEM**
1. Ajustes → Mostrar funciones avanzadas → **Reparto central**: dirección (ej. `http://PC-OFICINA:8765`) y su token. Guardar y reabrir.
2. En la Cola pulsar **Disponible**. Solo recibe con la aplicación abierta y Disponible, una solicitud a la vez,
   por turno (el que lleva más tiempo sin recibir). El lector de correo sigue en su PC (fase 2 lo centraliza).
3. Al documentar, el Est_Seg lo escribe el central en SharePoint.

Seguridad: cada PEM tiene su token (cifrado en su PC). En la red interna va por HTTP; en Azure irá por HTTPS.

## Pruebas
    python -m unittest discover -s tests -v
Usan una carpeta temporal (`HAC_ZAC_DATOS`); no tocan datos reales.

## Registros
`hac_zac.log` en la carpeta de datos (rotativo, 1 MB x 3).

## Problemas con Chrome
Ejecute `python diagnostico_navegador.py` y revise la salida. Perfiles en `%LOCALAPPDATA%\hac_zac\`.

## Seguridad
- Las credenciales se escriben solo en **Ajustes**. Nunca en el código: una prueba falla si el script trae una clave.
- Las claves se guardan en `credenciales.json` cifradas con DPAPI de Windows (`hac_zac_dpapi.py`): solo su usuario
  de Windows, en su PC, puede leerlas. Si cambia de PC o de usuario, vuelva a escribirlas en Ajustes.
- Datos de trabajo (`historial_capa2.json`, cola, ajustes, credenciales, registros) están en `.gitignore`.
- Cada escritura en SharePoint (asignación y Est_Seg) queda en `registro_sharepoint.jsonl` con el valor anterior,
  para revisar o deshacer a mano.
