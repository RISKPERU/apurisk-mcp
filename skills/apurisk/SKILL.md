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

## Abrir ventanas de la cinta

`apurisk_list_windows` lista lo disponible y `apurisk_open_window(name)` lo abre en Excel (por ejemplo `RegistroRiesgos`, `BowTie`, `VerHeatMap`, `Simular`, `Dashboard`, `Wbs`, `Rbs`). Abrir una ventana la deja en pantalla para la persona; no devuelve datos.

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
