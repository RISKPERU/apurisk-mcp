# apurisk-mcp

Servidor [MCP](https://modelcontextprotocol.io) para que Claude use el add-in **ApuRisk** dentro de Excel: encontrar un Excel abierto (o abrir un libro), comprobar si ApuRisk está instalado y cargado, registrar y consultar riesgos en el Registro del libro y abrir las ventanas de la cinta.

Tiene tres piezas:

| Pieza | Dónde | Qué hace |
|---|---|---|
| Servidor MCP | `src/apurisk_mcp` | Herramientas `apurisk_*` (Python, COM con pywin32). |
| Skill | `skills/apurisk/SKILL.md` | Enseña a Claude cómo funciona ApuRisk (vocabulario, flujo, prudencia). |
| Puerta del add-in | add-in ApuRisk (`Automation/ApuriskAutomation.cs`) | Función oculta `APURISK_AUTOMATION` de Excel que ejecuta los servicios reales de ApuRisk. |

El servidor **no escribe en las hojas por su cuenta**: pasa por el add-in, que aplica las validaciones, asigna los IDs (`R-001`…) y respeta la protección de las tablas. No abre puertos de red: habla con Excel por COM, dentro de tu sesión de Windows.

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
