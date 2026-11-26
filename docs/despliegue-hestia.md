# Piloto MCP remoto en HestiaCP

Este despliegue usa **un VPS y una sola PC Windows con Excel**. El VPS expone
`https://mcp.TU-DOMINIO/mcp`; la PC ejecuta `apurisk-mcp-agent` y mantiene una
conexión saliente. El VPS no ejecuta Excel. El MCP local por `stdio` continúa
disponible sin cambios.

## Alcance del piloto

Herramientas remotas: `apurisk_status`, `apurisk_list_risks`,
`apurisk_get_risk`, `apurisk_bowtie_get`, `apurisk_select_risk` y las
herramientas `apurisk_simulation_*` para controlar las cuatro vistas, ejecutar,
consultar el resumen numérico y exportar a Excel. Se excluyen los comandos
genéricos y las escrituras al Registro. La exportación sí crea hojas en el
libro activo. Se requiere instalar también la versión del add-in con los
comandos `simulation.result.*` y `simulation.export.status`; el motor y la
exportación se ejecutan en la PC con Excel abierto. El gateway usa memoria de
un solo proceso, un solo agente y **dos claves compartidas**. No usar la misma
clave para varias personas o computadoras; antes de un despliegue multiusuario
se necesita identidad individual, autorización por usuario y enrutamiento por
dispositivo.

## 1. VPS Linux

Crear un subdominio en Hestia, apuntar DNS al VPS y activar SSL de Let's Encrypt.
Claude requiere HTTPS público en puerto 443. Instalar Python 3.10 o superior,
Git y los paquetes necesarios para crear entornos virtuales. Como administrador:

```bash
useradd --system --user-group --home /opt/apurisk-mcp --shell /usr/sbin/nologin apurisk
git clone https://github.com/RISKPERU/apurisk-mcp.git /opt/apurisk-mcp
cd /opt/apurisk-mcp
python3 -m venv .venv
.venv/bin/pip install '.[remote]'
chown -R apurisk:apurisk /opt/apurisk-mcp
```

**Antes de clonar en el VPS**, publicar la rama que contiene este piloto o
subir el ZIP de entrega y extraerlo en `/opt/apurisk-mcp`. `origin/main`
todavía no incluye estos archivos.

Generar **dos secretos diferentes** (por ejemplo, `openssl rand -hex 32`).
Crear `/etc/apurisk-mcp.env` con permisos `0600`:

```ini
APURISK_MCP_PUBLIC_HOST=mcp.TU-DOMINIO
APURISK_MCP_CLIENT_TOKEN=REEMPLAZAR_CON_SECRETO_1
APURISK_MCP_AGENT_TOKEN=REEMPLAZAR_CON_SECRETO_2
```

`APURISK_MCP_PUBLIC_HOST` es el dominio sin `https://`. Es obligatorio: el SDK de
MCP solo acepta `Host: localhost` por omisión y, detrás del proxy, respondería
`421 Invalid Host header`.

Copiar `deploy/apurisk-mcp.service.example` a
`/etc/systemd/system/apurisk-mcp.service`, luego:

```bash
systemctl daemon-reload
systemctl enable --now apurisk-mcp
systemctl status apurisk-mcp
curl http://127.0.0.1:8765/health
```

Mantener el puerto 8765 ligado a `127.0.0.1`; no abrirlo en el firewall.
El servicio **debe tener un solo worker**, porque la cola del piloto reside en
memoria. Tras un reinicio, el agente local volverá a conectarse solo.

## 2. Proxy HestiaCP

Usar el dominio recién creado. Copiar su plantilla Nginx actual a un nombre
propio para `.tpl` y `.stpl`; la ubicación depende de si Hestia usa Nginx solo,
Nginx + PHP-FPM o Nginx + Apache. En la plantilla HTTP (`.tpl`), redirigir
`location /` a HTTPS (`return 301 https://$host$request_uri;`). Solo en la
plantilla HTTPS (`.stpl`), sustituir el bloque `location /` por el contenido de
`deploy/hestia/proxy-location.example.conf`. Seleccionar la plantilla nueva
para el dominio en Hestia y reconstruir su configuración. No editar la
plantilla predeterminada ni el archivo de dominio generado, porque Hestia lo
sobrescribe al reconstruir. Comprobar con `nginx -t` antes de recargar Nginx.

```bash
curl https://mcp.TU-DOMINIO/health
# /mcp existe, pero debe rechazar a quien no tenga el token:
curl -i https://mcp.TU-DOMINIO/mcp
```

El último comando debe devolver `401`. También `/agent/next` debe devolver
`401` sin la clave del agente. No publicar las claves en Git, logs ni capturas.

## 3. Agente en la PC Windows

En la PC debe estar Excel de escritorio, el add-in ApuRisk con la puerta
`APURISK_AUTOMATION` y los comandos de resultados de Simulación, y un libro de
prueba abierto. Instalar este repositorio
con Python 3.10+ y ejecutar en PowerShell (preferir variables de entorno
protegidas por el usuario; los valores de abajo son marcadores):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
$env:APURISK_MCP_URL = 'https://mcp.TU-DOMINIO'
$env:APURISK_MCP_AGENT_TOKEN = 'REEMPLAZAR_CON_SECRETO_2'
.venv\Scripts\apurisk-mcp-agent.exe
```

El agente debe ejecutarse **en la sesión interactiva del mismo usuario de
Windows que tiene Excel abierto**. No instalarlo como servicio del sistema:
un servicio en otra sesión no encontrará ese Excel por COM. Mantener la
consola abierta para el piloto; el agente reintenta si se corta la red.

## 4. Claude en Excel

En Claude, crear un conector personalizado con URL
`https://mcp.TU-DOMINIO/mcp`. Usar la opción de autenticación mediante
cabecera fija, con `Authorization: Bearer SECRETO_1`. En planes Team o
Enterprise, el administrador debe añadir primero el conector a la
organización. Activarlo en la conversación de Claude en Excel.

Prueba de extremo a extremo: pedir `apurisk_status`, abrir Simulación con
`apurisk_simulation_open`, ejecutar con `apurisk_simulation_run`, leer el
resumen con `apurisk_simulation_results` y exportar con
`apurisk_simulation_export`. Comprobar en Excel las hojas `Sim Resumen`,
`Sim Riesgos`, `Sim Gráficos` y `Sim Iteraciones`. Si el agente se detiene,
el MCP responderá que está desconectado.

## Limitaciones antes de producción

El piloto no ofrece OAuth, cuentas separadas, alta disponibilidad, cola
persistente ni controles de aprobación para operaciones de escritura. La
cabecera fija del conector es una credencial compartida: en una organización
todos los usuarios habilitados podrían llegar al mismo agente. Para producción
separar identidades y permisos, rotar claves, limitar herramientas por usuario,
auditar acciones y registrar varios agentes de forma explícita.
