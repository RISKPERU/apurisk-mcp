---
name: apurisk
description: Cómo funciona ApuRisk (add-in de Excel para gestión de riesgos) y cómo usarlo con las herramientas apurisk_* — registrar y consultar riesgos, abrir ventanas de la cinta, comprobar si Excel y el add-in están listos.
---

# ApuRisk con Claude

ApuRisk es un add-in de Excel (cinta «Apurisk») para gestionar riesgos de proyecto: Registro de riesgos, evaluación con matriz, BowTie, acciones de respuesta, mapa de calor, simulación y reportes. Los datos viven **dentro del libro de Excel**, en tablas protegidas; las herramientas `apurisk_*` hablan con el add-in, que aplica sus validaciones, asigna los IDs y respeta la protección de hojas. **No escribas en las hojas por otra vía**: se saltaría esas reglas.

## Antes de actuar

1. `apurisk_status` — ¿hay Excel abierto?, ¿qué libros?, ¿está ApuRisk cargado en cada uno (`apurisk.loaded`)?
   - Sin Excel → `apurisk_open_workbook(path)` lo abre (o inicia Excel).
   - Excel abierto pero `loaded: false` → `installed` dice si está instalado; si lo está, `apurisk_load_addin`. Si no está instalado, dilo: se instala con el instalador del add-in (no lo instales tú).
   - Varios Excel → pasa `instance` (el identificador que muestra `apurisk_status`).
2. Todo opera sobre el **libro activo**. Si hay varios libros, confirma cuál con la persona o actívalo con `apurisk_activate_workbook`.
3. Un libro nuevo no tiene Registro: `apurisk_create_register`. Si falla, el error lista qué falta (datos del proyecto, escalas, criterios sin confirmar…). Eso se configura en las ventanas de la cinta (`apurisk_open_window("Proyecto")`, `"EscalaProbabilidad"`, `"ConfigurarMatriz"`…); explícaselo a la persona en lugar de intentar rodearlo.

## Registrar riesgos

`apurisk_create_risk` crea el riesgo **en borrador** y escribe los campos; el ID (`R-001`…) lo asigna ApuRisk. Un riesgo solo se puede publicar (`identified`) si está completo; si no, el add-in rechaza con la lista de lo que falta (WBS, RBS, Fuente, Inicio/Fin de exposición, Responsable). **Crea en borrador y publica solo si la persona lo pide** (`publish=true` o `apurisk_set_risk_status`).

Redacta bien el riesgo: *causa → evento → consecuencia* («Debido a… puede ocurrir… lo que provocaría…»). `RiskName` corto, `Event` lo que sucede, `Cause` y `Consequence` aparte. No inventes responsables, WBS ni RBS: si no los conoces, déjalos vacíos y dilo.

### Vocabulario

- **Tipo** (`RiskType`): `Threat` (amenaza), `Opportunity` (oportunidad), `Issue` (problema ya materializado: no usa probabilidad futura).
- **Estados**: `draft` → `identified` → `evaluating` → `treating` → `monitoring` → `closed`; `archived`. Las transiciones permitidas de cada riesgo vienen en `allowedTransitions`.
- **Campos editables**: `RiskName, RiskType, Cause, Event, Consequence, Category, SourceType, SourceDetail, IdentifiedDate (AAAA-MM-DD), ExposureStart, ExposureEnd, WbsId, RbsId, RiskOwnerId`. Todo es texto.
- **Calculados (solo lectura)**: todo lo que empieza por `Current.` (nivel de matriz, apetito, estado de evaluación), validación, auditoría. Los produce la evaluación, no se editan.

## Que la persona lo vea en pantalla

Lo que cambias por las herramientas queda en el libro, pero la persona trabaja en las ventanas de ApuRisk. Para que lo vea:

- `apurisk_select_risk(risk_id)` abre el Registro y deja **seleccionado** ese riesgo; con `show="bowtie"` o `"evaluate"` abre además su BowTie o su Evaluación.
- **Las ventanas abiertas se actualizan solas** cuando una herramienta cambia datos (Registro, BowTie, Matriz): no hace falta pedir nada. Si la persona editó Excel a mano y no lo ve, `apurisk_refresh_windows` las hace releer. `apurisk_windows` dice cuáles están abiertas.
- Si la persona está editando en la ventana (cambios sin guardar), esa ventana no pisa lo que escribe; lo tuyo aparece cuando termina de guardar y la ventana vuelve a primer plano.

## BowTie

`apurisk_bowtie_get(risk_id)` lee el BowTie del riesgo (peligro, evento tope, causas/amenazas, consecuencias y barreras). `apurisk_bowtie_edit` lo crea si no existe y **agrega**: causas, consecuencias, barreras (preventivas en las causas, mitigantes en las consecuencias) y cambia peligro o evento tope. No borra ni reordena. Las probabilidades de ruta se piden en % (0-100) y son supuestos causales, no el nivel del riesgo. Por defecto abre el BowTie en pantalla (`show=true`).

Las barreras nuevas quedan «Proposed» (propuestas); documentarlas, asignar responsables y evaluarlas lo hace la persona.

## Matriz de riesgos (mapa de calor)

`apurisk_matrix_view` abre la Matriz y cambia lo que muestra como si pulsara sus botones: perfil (amenazas/oportunidades), escenario (Inherente/Vigente/Residual), perspectiva, buscador, los tres filtros rápidos (fuera de tolerancia, desactualizadas, borradores) y el orden. `apurisk_matrix_select` selecciona un riesgo o una celda (probabilidad × impacto) y puede abrir su Evaluación. La Matriz es de consulta: no cambia datos.

## Abrir ventanas de la cinta

`apurisk_list_windows` lista lo disponible y `apurisk_open_window(name)` lo abre en Excel (por ejemplo `RegistroRiesgos`, `BowTie`, `VerHeatMap`, `Simular`, `Dashboard`, `Wbs`, `Rbs`). Abrir una ventana la deja en pantalla para la persona.

## Simulación actual

Usa `apurisk_simulation_open` para abrirla. Sus pasos son Riesgos, Correlaciones, Simulación y Resultados; `apurisk_simulation_view` navega entre ellos y puede releer el libro. `apurisk_simulation_focus` enfoca un riesgo o vuelve a todos. `apurisk_simulation_configure` ajusta iteraciones, semilla y método; `apurisk_simulation_risk` incluye riesgos o cambia su probabilidad solo en esta simulación; `apurisk_simulation_correlation` ajusta o quita correlaciones entre entradas `cost:R-001` y `time:R-001`. Ejecuta con `apurisk_simulation_run` y responde preguntas numéricas usando el resumen devuelto o `apurisk_simulation_results`, con medias, percentiles y sensibilidad por riesgo. `apurisk_simulation_explore` cambia los objetivos, histograma e iteración visible. `apurisk_simulation_export` pulsa el botón de la vista y crea hojas en el libro activo. El resumen MCP no incluye cada muestra ni imágenes de gráficos; esas se ven en la vista y en la exportación. Si la operación devuelve `pending`, consulta de nuevo el estado.

## Comandos avanzados

`apurisk_bridge(type, payload)` ejecuta los mismos comandos que usan las ventanas (el `workbookScopeId` se completa solo). Algunos útiles:

- `riskRegister.list`, `riskRegister.history`, `riskRegister.undo` / `redo`
- `riskEvaluation.overview`, `riskEvaluation.form`, `riskEvaluation.preview`, `riskEvaluation.saveDraft`, `riskEvaluation.confirm`
- `riskActions.list`, `riskActions.save`, `riskActions.delete`
- `riskRegister.openBowTie`, `heatMap.openEvaluation` (abren ventanas)

Los errores traen un código estable (`conflict`, `invalid_transition`, `row_blocked`…) y un mensaje pensado para la persona: transmítelo tal cual. Un `conflict` significa que la fila cambió en Excel: vuelve a leerla (`apurisk_get_risk`) y reintenta.

## Reglas de prudencia

- Confirma antes de acciones que cambian muchos riesgos o estados; crear borradores uno a uno es seguro, publicar o cerrar en bloque no.
- Si Excel responde `excel_busy`, hay una celda en edición o un cuadro de diálogo abierto: pídele a la persona que lo cierre.
- No guardes ni cierres libros por tu cuenta.


## Análisis del proyecto (consultas, no cambian nada)

Para responder preguntas de seguimiento usa estas herramientas en lugar de armar el análisis a mano; cada una dice con qué criterio calcula y qué falta.

| Pregunta | Herramienta |
|---|---|
| ¿Qué riesgos prioritarios están incompletos, sin responsable o sin actualizar? | `apurisk_risk_health(priority_only=True)` |
| ¿Qué subió de nivel desde la última revisión, y por qué (probabilidad, impacto, controles)? | `apurisk_risk_changes` |
| ¿Qué acciones están vencidas o vencen pronto? | `apurisk_actions_due(days=7)` |
| Todo sobre un riesgo y qué información falta para decidir | `apurisk_risk_dossier(risk_id)` |

- **«Prioritario»** = nivel actual Extremo, Alto o Prioritaria. **«Última revisión»** = la revisión confirmada anterior de la evaluación (Actual).
- Los responsables vienen con su nombre (`m1`, `m2`… son ids). Cita a la persona por su nombre.
- **Controles** = las barreras del BowTie: `Operational` (operativa), `Partial` (parcial), `Proposed` (solo propuesta). Si un control es solo propuesto, no lo cuentes como protección.
- Un riesgo con **una sola revisión** no permite decir qué cambió: dilo, no lo supongas. Lo mismo con un riesgo sin evaluación Residual: no hay cuánto baja con las acciones.
- Si una herramienta devuelve `informacionFaltante`, **inclúyelo en la respuesta**: es lo que la persona pide cuando pregunta «qué datos faltan».
- «Fecha de referencia»: las herramientas usan la fecha de hoy; pásala en `today` (AAAA-MM-DD) solo si la persona la indica.
