# Guion de la demostración (Claude Desktop + ApuRisk MCP + libro demo)

## Antes de empezar

1. Instalar el add-in nuevo (ZIP `Instalador_Apurisk_*.zip` → `INSTALADOR.bat`) y actualizar el MCP (`Instalar-ApuRisk-MCP.cmd` en `apurisk-mcp`). Cerrar y volver a abrir Claude Desktop.
2. Abrir en Excel **`C:\System\Work\Apurisk - Proyecto Demo.xlsx`** (ya preparado). Dejarlo como libro activo y con el add-in cargado.
3. Primera frase en Claude: *«Revisa si ApuRisk está listo»* (usa `apurisk_status`).


## Qué hay en el libro (a propósito)

| Pregunta | Lo que encontrará |
|---|---|
| 1. Prioritarios incompletos / sin responsable / > 30 días | **R-027** (Alto) sin responsable; **R-021** (Alto) sin causa; **R-024** (46 días) y **R-026** (41 días) sin actualizar. |
| 2. Subieron de nivel desde la última revisión | **R-005** Medio→Alto (prob. 40→55 y plazo 3→4); **R-031** Alto→Extremo (financiero 3→4, plazo 4→5). Sin cambio de nivel pero con otra probabilidad: R-002, R-003, R-004, R-006. **R-028** bajó (Medio→Bajo). |
| 3. Acciones vencidas / por vencer (a 20/11/2026) | Vencidas: A-001 (R-001, 8 d), A-015 (R-004, 4 d), A-038 (R-031, 2 d). Por vencer: A-018, A-013, A-004, A-025. |
| 5. Tres riesgos de la semana | Combina lo anterior. `apurisk_risk_dossier` trae por riesgo lo que **falta** (sin residual, controles solo propuestos, acciones sin avance…). |

## Preguntas (tal como las harás) y qué herramienta usará Claude

1. *«¿Qué riesgos prioritarios tienen información incompleta, carecen de responsable o llevan más de 30 días sin actualizarse?»* → `apurisk_risk_health(priority_only=True)`
2. *«¿Qué riesgos aumentaron de nivel desde la última revisión? ¿Cambió su probabilidad, su impacto o la evaluación de sus controles?»* → `apurisk_risk_changes`
3. *«¿Qué acciones de mitigación están vencidas o vencen en los próximos siete días? Indica el riesgo asociado, el responsable y la fecha.»* → `apurisk_actions_due`
5. *«Revisa el registro de riesgos y el estado de los controles y las acciones… tres riesgos que requieren atención esta semana…»* → `apurisk_risk_health` + `apurisk_risk_changes` + `apurisk_actions_due` + `apurisk_risk_dossier` por riesgo

## Límites que conviene conocer (Claude los dirá; mejor que no te sorprendan)

- **Controles:** se leen del BowTie (Operativa / Parcial / Propuesta). No se compara el historial de revisiones de controles: no hay ninguna registrada en este libro.
- **«Fecha contractual»:** el libro solo tiene la fecha de fin del proyecto (20/12/2027); Claude la usará como tal.
- Las fechas del libro están calculadas para el **20/11/2026**. Si la demo es otro día, vuelve a generarlo (ver abajo).

## Restaurar o regenerar el libro

```powershell
# Copia limpia del original y preparación (con Excel y ApuRisk cargado)
copy "C:\System\Work\RiskPerú\demo-work\Apurisk - Proyecto Demo (ORIGINAL).xlsx" C:\System\Work\RiskPerú\demo-work\demo-trabajo.xlsx
python demo\preparar_demo.py "C:\System\Work\RiskPerú\demo-work\demo-trabajo.xlsx" --hoy 2026-11-20
```

El script siempre debe partir de la copia limpia (aplicarlo dos veces añade revisiones).
