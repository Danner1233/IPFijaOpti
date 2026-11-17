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

## Reparto central (fases 1 y 2)
Un PC (luego Azure) reparte las solicitudes y lee el correo; los PEM ya no abren SharePoint ni Outlook.

**Administrador (PC central)**
1. Registrar a cada PEM con el nombre EXACTO de la columna PEM_ASIGNADO; muestra su token:
   `py -3 servidor_central.py --agregar "Nombre Apellido"`  (`--lista`, `--token "Nombre"` para cambiarlo, `--quitar`)
2. Primera vez, en simulación (inicia sesión en SharePoint y solo muestra a quién asignaría):
   `py -3 servidor_central.py --simular --ver`
3. De verdad: `py -3 servidor_central.py`. Abre dos navegadores: SharePoint y Outlook (el correo llega a
   todos los PEM, así que basta un buzón). Cada 60 s busca la cuenta RR de las asignaciones sin plantilla y la
   une solo si el SOLICITUD ID coincide. Opciones: `--sin-correo`, `--correo-cada 60`, `--debug-correo`.
   Windows preguntará por el Firewall: permitir en **redes privadas**.
   Datos del central: `%LOCALAPPDATA%\hac_zac\central` (aparte de los de la aplicación, aunque sea el mismo PC).

**Cada PEM**
1. Ajustes → Mostrar funciones avanzadas → **Reparto central**: dirección (ej. `http://PC-OFICINA:8765`) y su token. Guardar y reabrir.
2. En la Cola pulsar **Disponible**. Solo recibe con la aplicación abierta y Disponible, una solicitud a la vez,
   por turno (el que lleva más tiempo sin recibir). La plantilla del correo llega sola (aviso "Plantilla lista").
3. Al documentar, el Est_Seg lo escribe el central en SharePoint.

Seguridad: cada PEM tiene su token (cifrado en su PC). En la red interna va por HTTP; en Azure irá por HTTPS.

## Agente del técnico por WhatsApp (fase 3)
El PEM no habla con el técnico: el agente le avisa cuando se asigna su solicitud, le responde el estado, le pasa
**literal** lo que el PEM escriba (mensaje o direccionamiento final), le avisa el cierre y le pregunta si quedó en orden.
Lo que no sabe responder se lo pasa al PEM (aviso en la Cola y recuadro "Técnico").

**Barreras en código:** la IA (gpt-5-mini) solo clasifica la intención del mensaje; las respuestas son textos fijos con
datos reales; IP y observaciones solo se reenvían tal como las escribió el PEM; cada técnico solo ve su caso (por el
celular de la solicitud); a la IA solo le llega el texto del técnico. Sin IA, entiende por palabras clave.

**Probar sin Meta (simulador):**
1. `py -3 servidor_central.py --archivo items.json --demo --whatsapp-simulado` (o con SharePoint, sin `--archivo`)
2. En otra ventana: `py -3 chat_tecnico.py --tel 3001234567` y escriba como si fuera el técnico.

**WhatsApp real (Cloud API de Meta; no sirve la app WhatsApp Business):**
1. developers.facebook.com → Crear app (tipo Empresa) → agregar **WhatsApp**. Meta da un número de prueba gratis
   que puede escribir a hasta 5 celulares que usted verifique. La SIM nueva se agrega después como número real
   (no debe estar registrada en ninguna app de WhatsApp).
2. `py -3 servidor_central.py --configurar-whatsapp` (phone_number_id, token, verify token, clave secreta de la app,
   plantilla de primer aviso: `hello_world` en pruebas, sin variable).
3. URL pública HTTPS hacia el central: `ngrok http 8765` (en Azure no hace falta).
4. En Meta → WhatsApp → Configuración → Webhook: URL `https://<ngrok>/whatsapp`, el mismo verify token; suscribir **messages**.

**IA (gpt-5-mini en Foundry):** `py -3 servidor_central.py --configurar-ia` (endpoint y despliegue; API key opcional,
si no se usa `az login`) y luego `py -3 servidor_central.py --probar-ia "me pasas la ip?"`.

## Equipo en línea y tiempo de gestión
**Equipo (pestaña Equipo):** en Ajustes → "Carpeta del equipo" se elige una carpeta de OneDrive/SharePoint que todos
los PEM tengan sincronizada (y su nombre en SharePoint en funciones avanzadas). Cada app publica cada minuto:
- **Activo**: usó la app (clic/tecla) en los últimos 5 min o tiene un proceso corriendo.
- **Ausente**: app abierta, 5 min sin uso. **Desconectado**: no publica hace más de 3 min.
- Se suman los minutos activos del día (sin contar ausencias). No se publica ningún dato de clientes.

**Tiempo de gestión:** corre desde que la solicitud se asigna (cola) hasta Documentar. Límite: **Claro 15 min**,
**ATP/ONNET 30 min**. Se ve en la plantilla (⏱ 12/15 min), en la Cola y en el Historial (filtro "Tiempo superado").
Al pasarse sale la alerta "Superó el tiempo de gestión · baja productividad" (una vez). Para documentar es
obligatorio justificar: **Claro** hasta 5 fotos (+ nota opcional), **neutras** una observación; en ambas
existe "Demora por parte del PEM". Las fotos se copian a `<carpeta de datos>\demoras\<solicitud>\`.

## Instalar en otros PC (un doble clic)
**Armar el paquete (administrador, en su PC):**
`py -3 armar_instalador.py --salida "<carpeta del equipo en OneDrive>\HAC_ZAC instalador"`
Deja `INSTALAR.bat` + `HAC_ZAC.zip` (~76 MB: programa, Python con todo lo necesario y la base de Capa 2).

**Cada PEM:** doble clic en `INSTALAR.bat`. Instala en `%LOCALAPPDATA%\HAC_ZAC` (fuera de OneDrive), busca SecureCRT y
la sesión del jump host, deja configurada la carpeta del equipo (la del instalador), crea el acceso directo
**HAC ZAC** en el escritorio y lo abre. La primera vez: en Ajustes, su nombre (como en SharePoint) y sus claves.

**Actualizar a todos:** volver a armar el paquete y que cada uno ejecute `INSTALAR.bat` otra vez (con HAC ZAC
cerrado). Se conservan ajustes, claves, cola, historial y fotos.

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
