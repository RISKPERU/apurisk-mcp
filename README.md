# apurisk-mcp

> **Piloto remoto para Claude en Excel:** el gateway HTTPS del VPS y el agente
> Windows que opera el Excel local están implementados en esta rama. Véase
> [despliegue en HestiaCP](docs/despliegue-hestia.md) y el estado abajo. El
> servidor local por `stdio` descrito más abajo sigue disponible.

## Piloto remoto: estado y cómo retomarlo

Esta sección resume lo decidido y desplegado (26/11/2026) para que cualquier
persona, o un agente de código, pueda continuar desde un clon nuevo. **Las
claves nunca van en el repositorio ni en el chat**: las tiene el responsable
guardadas aparte (`CLIENT_TOKEN` para Claude, `AGENT_TOKEN` para la PC).

### Qué es y por qué

Se replica el modelo del *@RISK Agent Connector* de Lumivero: un MCP remoto
por URL que se añade como **conector personalizado en Claude Desktop** y se usa
desde **Claude en Excel**. Como el VPS no tiene Excel, se divide en dos piezas:

```
Claude en Excel ──HTTPS──> VPS: gateway MCP (mcp.riskperu.com/mcp)
                                │ cola en memoria
PC Windows: agente ──HTTPS saliente (sondeo)──┘
   └─ COM ─> Excel + add-in ApuRisk (puerta APURISK_AUTOMATION)
```

- **Gateway** (`src/apurisk_mcp/remote.py`): FastMCP, HTTP *streamable*
  sin estado. Publica **las mismas herramientas que el MCP local** (nombre,
  parámetros y descripción, generadas de `apurisk_mcp.server`) y reenvía cada
  llamada al agente. Una herramienta nueva en el MCP local aparece sola.
- **Agente** (`src/apurisk_mcp/local_agent.py`): corre en la sesión del
  usuario de Windows con Excel abierto, sondea `/agent/next` y responde en
  `/agent/result`. No abre puertos en la PC. No puede ser un servicio de
  Windows (otra sesión no ve ese Excel por COM).
- **Autenticación del piloto**: dos claves compartidas. El formulario de
  conectores de Claude no admite cabeceras, así que la clave del cliente va en
  la URL (`?key=`); el agente usa `Authorization: Bearer`.

### Lo que ya está desplegado

| Dónde | Estado |
|---|---|
| DNS | Cloudflare, registro A `mcp.riskperu.com` → VPS, **solo DNS (nube gris)**. |
| VPS | Contabo, Ubuntu 24.04, HestiaCP (nginx + apache), usuario Hestia `riskperu`, dominio `mcp.riskperu.com` con Let's Encrypt y HTTPS forzado. |
| Código | `/opt/apurisk-mcp`, rama `demo-viernes`, dueño `apurisk` (usuario de sistema sin login), `.venv` con instalación editable `pip install -e '.[remote]'`. |
| Claves | `/etc/apurisk-mcp.env` (root, `0600`): `APURISK_MCP_PUBLIC_HOST`, `APURISK_MCP_CLIENT_TOKEN`, `APURISK_MCP_AGENT_TOKEN`. |
| Servicio | systemd `apurisk-mcp` (uvicorn en `127.0.0.1:8765`, **1 worker**, ver `deploy/apurisk-mcp.service.example`). |
| Proxy | `/home/riskperu/conf/web/mcp.riskperu.com/nginx.ssl.conf_apurisk`: `location ~ ^/(mcp\|agent/\|health)` → `127.0.0.1:8765`, `proxy_buffering off`, `proxy_read_timeout 75s`. Hestia conserva este include al reconstruir. |
| Claude | Conector personalizado en Claude Desktop con `https://mcp.riskperu.com/mcp?key=<CLIENT_TOKEN>`; aparece en Claude en Excel. Probado de extremo a extremo (34 herramientas, abrir Matriz, ventanas, etc.). |

### Poner en marcha una PC nueva (p. ej., la de la empresa)

1. Instalar el add-in ApuRisk desde `develop` del add-in (incluye la puerta de
   automatización y los comandos `simulation.result.*`). Comprobar que Excel
   carga la versión nueva (`%APPDATA%\ApuriskAddIn\Apurisk.ExcelAddIn64.xll`).
2. Clonar este repositorio y cambiar a `demo-viernes`.
3. Doble clic en **`Instalar-Agente-Remoto.cmd`**: pide la URL (Enter =
   `https://mcp.riskperu.com`) y la **clave del agente**. Deja el agente
   corriendo **sin ventana** (`pythonw.exe`), lo añade al inicio de sesión de
   Windows y crea en el escritorio *Iniciar/Detener agente ApuRisk*. Log en
   `%LOCALAPPDATA%\ApuriskMcp\agente.log`. Volver a ejecutarlo actualiza
   (Enter mantiene la clave); `-Uninstall` lo quita.
4. Verificar: `https://mcp.riskperu.com/health` debe decir `"agentConnected": true`.
5. En Claude Desktop, si el conector no existe en esa cuenta, añadirlo
   (*Customize → Connectors → + → Add custom connector*) con la URL de arriba.
   Abrir Excel con un libro y usar Claude en Excel con el conector activado.

**Un solo agente a la vez**: si quedó encendido en otra PC, detenerlo; dos
agentes se reparten las solicitudes y Claude acabaría operando otro Excel.

### Actualizar el servidor

Como root en el VPS (MobaXterm):

```bash
cd /opt/apurisk-mcp && git pull && chown -R apurisk:apurisk /opt/apurisk-mcp && systemctl restart apurisk-mcp
curl -s https://mcp.riskperu.com/health
```

Si cambian dependencias: `/opt/apurisk-mcp/.venv/bin/pip install -e '.[remote]'`
antes de reiniciar. Si cambian las herramientas, reiniciar también el agente de
la PC (volver a ejecutar el instalador) y abrir **una conversación nueva** en
Claude, que guarda la lista de herramientas del conector.

### Problemas ya vistos

| Síntoma | Causa / solución |
|---|---|
| `421 Invalid Host header` | Falta `APURISK_MCP_PUBLIC_HOST` (el SDK de MCP solo acepta `localhost` por omisión). |
| `git pull` → *dubious ownership* | Una vez: `git config --global --add safe.directory /opt/apurisk-mcp`. |
| `502` justo tras reiniciar | El servicio aún arrancaba; repetir en unos segundos. |
| Claude dice que no existe una herramienta o comando | Servidor con código viejo (pip no editable) o conversación de Claude con la lista anterior; o el add-in instalado es antiguo («Comando no registrado o no autorizado»). |
| `agentConnected: false` | El agente no corre: ver `agente.log`, la clave del agente o la red. |

### Pendiente

- **Seguridad antes de más usuarios**: hoy quien tenga la URL con la clave
  controla ese Excel, escrituras incluidas (Registro, BowTie, `apurisk_bridge`).
  Para producción: OAuth por usuario (como MyLumivero), un agente por
  usuario/PC con enrutamiento, cola persistente y auditoría.
- Llevar `demo-viernes` a `main` de este repositorio.
- En el add-in, el merge de `demo-viernes` a `develop` (PR #38, commit
  `d53105e`) es **temporal**: revertir con `git revert -m 1 d53105e` cuando
  llegue la versión definitiva.

Servidor [MCP](https://modelcontextprotocol.io) para que Claude use el add-in **ApuRisk** dentro de Excel: encontrar un Excel abierto (o abrir un libro), comprobar si ApuRisk está instalado y cargado, registrar y consultar riesgos en el Registro del libro y abrir las ventanas de la cinta.

Tiene tres piezas:

| Pieza | Dónde | Qué hace |
|---|---|---|
| Servidor MCP | `src/apurisk_mcp` | Herramientas `apurisk_*` (Python, COM con pywin32). |
| Skill | `skills/apurisk/SKILL.md` | Enseña a Claude cómo funciona ApuRisk (vocabulario, flujo, prudencia). |
| Puerta del add-in | add-in ApuRisk (`Automation/ApuriskAutomation.cs`) | Función oculta `APURISK_AUTOMATION` de Excel que ejecuta los servicios reales de ApuRisk. |

El servidor **no escribe en las hojas por su cuenta**: pasa por el add-in, que aplica las validaciones, asigna los IDs (`R-001`…) y respeta la protección de las tablas. En el modo local por `stdio` no abre puertos de red: habla con Excel por COM, dentro de tu sesión de Windows.

## Requisitos

- Windows con Excel de escritorio y el add-in ApuRisk **con la puerta de automatización** (versión de `develop` posterior al 18/11/2026). Con un add-in anterior, `apurisk_status` indica «el add-in no está cargado o es una versión anterior».
- Python 3.10+.

## Instalación (doble clic)

1. En GitHub: **Code → Download ZIP** y extrae la carpeta (o clona el repositorio).
2. Haz doble clic en **`Instalar-ApuRisk-MCP.cmd`**. Si Windows avisa de un archivo descargado, elige «Más información → Ejecutar de todas formas».
3. Cierra y vuelve a abrir Claude Code.

El instalador busca Python 3.10+ (si falta, lo instala con winget), crea su entorno en `%LOCALAPPDATA%\ApuriskMcp`, instala el servidor, copia el skill a `~\.claude\skills\apurisk` y lo registra en Claude Code (necesita el comando `claude`). Se puede volver a ejecutar para actualizar. No requiere privilegios de administrador.

Para quitarlo: `claude mcp remove apurisk --scope user` y borrar `%LOCALAPPDATA%\ApuriskMcp` y `~\.claude\skills\apurisk`.

## Instalación manual

```powershell
git clone https://github.com/RISKPERU/apurisk-mcp.git
cd apurisk-mcp
py -m venv .venv
.venv\Scripts\python -m pip install -e .
```

Registrarlo en Claude Code:

```powershell
$python = ("$PWD\.venv\Scripts\python.exe").Replace('\', '\\')
claude mcp add-json apurisk --scope user "{`"type`":`"stdio`",`"command`":`"$python`",`"args`":[`"-m`",`"apurisk_mcp.server`"]}"
```

Instalar el skill (para que Claude conozca ApuRisk):

```powershell
Copy-Item -Recurse skills\apurisk "$env:USERPROFILE\.claude\skills\apurisk"
```

## Herramientas

| Herramienta | Para qué |
|---|---|
| `apurisk_status` | Diagnóstico: Excel abierto, libros, ApuRisk instalado y cargado. Empezar por aquí. |
| `apurisk_open_workbook`, `apurisk_activate_workbook` | Abrir o activar un libro. |
| `apurisk_load_addin` | Cargar ApuRisk en un Excel donde no esté cargado. |
| `apurisk_list_windows`, `apurisk_open_window` | Ventanas y funciones de la cinta (Registro, BowTie, mapa de calor, simulación…). |
| `apurisk_simulation_open`, `apurisk_simulation_view`, `apurisk_simulation_focus` | Abren Simulación, muestran sus cuatro pasos, releen el libro y enfocan un riesgo. |
| `apurisk_simulation_configure`, `apurisk_simulation_risk`, `apurisk_simulation_correlation` | Ajustan muestreo, riesgos incluidos y correlaciones en la vista. |
| `apurisk_simulation_run`, `apurisk_simulation_results` | Ejecutan y leen el resumen numérico de la última simulación: estadísticos y sensibilidad por riesgo. |
| `apurisk_simulation_explore`, `apurisk_simulation_export` | Manejan objetivos, devuelven su probabilidad, muestran iteraciones y pulsan Exportar a Excel. |
| `apurisk_create_register` | Crear las tablas del Registro en el libro activo. |
| `apurisk_list_risks`, `apurisk_get_risk` | Consultar el Registro. |
| `apurisk_create_risk`, `apurisk_update_risk`, `apurisk_set_risk_status` | Registrar y cambiar riesgos (siempre en borrador salvo que se pida publicar). |
| `apurisk_select_risk` | Abrir el Registro con un riesgo seleccionado (y, si se pide, su BowTie o su Evaluación) para que la persona lo vea. |
| `apurisk_bowtie_get`, `apurisk_bowtie_edit` | Leer y ampliar el BowTie de un riesgo (causas, consecuencias, barreras, peligro, evento tope). |
| `apurisk_matrix_view`, `apurisk_matrix_select` | Manejar la Matriz de riesgos como con sus botones: perfil, escenario, filtros, orden, selección de celda o riesgo. |
| `apurisk_windows`, `apurisk_refresh_windows` | Ver qué ventanas hay abiertas y pedirles que relean el libro. |
| `apurisk_risk_health` | Riesgos incompletos, sin responsable, con evaluación pendiente o sin actualizar hace más de N días (con filtro de prioritarios). |
| `apurisk_risk_changes` | Qué riesgos cambiaron desde la última revisión de su evaluación y qué cambió: nivel, probabilidad, impacto por perspectiva; estado de sus controles. |
| `apurisk_actions_due` | Acciones vencidas o que vencen en los próximos N días, con riesgo, responsable (por nombre) y fecha. |
| `apurisk_risk_dossier` | Ficha de un riesgo (niveles por escenario, cambios, controles, acciones, cuantificación) y la lista de información que falta para decidir. |
| `apurisk_bridge` | Cualquier comando del puente de ApuRisk (evaluación, acciones…). |

Todas operan sobre el **libro activo**; con varios Excel abiertos se indica `instance` (lo muestra `apurisk_status`).

## Desarrollo

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Las pruebas usan un add-in simulado; la verificación real se hace contra Excel con el `.xll` empaquetado.
