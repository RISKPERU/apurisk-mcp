"""Servidor MCP (stdio). Cada herramienta es una acción concreta sobre Excel o ApuRisk; todo lo demás lo decide el add-in."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import analysis, automation, bowtie, excel, install_check, risks
from .automation import ApuriskError

mcp = FastMCP(
    "apurisk",
    instructions=(
        "Controla el add-in ApuRisk dentro de Excel. Empieza con apurisk_status para ver si hay un Excel abierto y si ApuRisk está "
        "cargado. Las acciones usan el libro ACTIVO de Excel. Los riesgos se crean en borrador; publícalos solo si la persona lo pide. "
        "Consulta el skill «apurisk» para el vocabulario (tipos de riesgo, estados, campos)."
    ),
)


def _context(instance: int | None) -> tuple[Any, automation.Runner, str]:
    """Excel elegido, su puerta al add-in y el identificador del libro activo (donde se escribe el Registro)."""
    app = excel.select_app(instance)
    run = excel.runner(app)
    scope = automation.status(run).get("workbookScopeId")
    if not scope:
        raise ApuriskError("no_workbook", "Excel no tiene ningún libro activo. Abre uno con apurisk_open_workbook.")
    return app, run, scope


@mcp.tool()
def apurisk_status() -> dict[str, Any]:
    """Diagnóstico: ¿hay Excel abierto?, ¿qué libros?, ¿ApuRisk está instalado y cargado en cada Excel? Úsalo primero."""
    return {
        "installed": install_check.installed(),
        "excelInstances": [excel.describe(app) for app in excel.running_apps()],
    }


@mcp.tool()
def apurisk_open_workbook(path: str, instance: int | None = None) -> dict[str, Any]:
    """Abre un libro de Excel (o lo activa si ya está abierto). Si no hay Excel abierto, inicia uno. Devuelve el estado de ApuRisk en él."""
    app, workbook = excel.open_workbook(path, instance)
    return {"opened": workbook.Name, **excel.describe(app)}


@mcp.tool()
def apurisk_activate_workbook(name: str, instance: int | None = None) -> dict[str, Any]:
    """Activa un libro ya abierto por su nombre (por ejemplo «Mina.xlsx»). Las demás acciones usan el libro activo."""
    app = excel.select_app(instance)
    excel.activate_workbook(app, name)
    return excel.describe(app)


@mcp.tool()
def apurisk_load_addin(instance: int | None = None, xll_path: str | None = None) -> dict[str, Any]:
    """Carga el add-in ApuRisk en un Excel donde no esté cargado (por ejemplo, uno iniciado por automatización). Usa el .xll instalado si no se indica ruta."""
    app = excel.select_app(instance)
    if xll_path is None:
        candidates = [item for item in install_check.installed() if item["channel"] == "current" and item["fileExists"]]
        if not candidates:
            raise ApuriskError("not_installed", "ApuRisk no está instalado para este usuario: instálalo con el instalador del add-in o indica xll_path.")
        xll_path = str(candidates[0]["path"])
    excel.load_addin(app, xll_path)
    return excel.describe(app)


@mcp.tool()
def apurisk_list_windows(instance: int | None = None) -> list[str]:
    """Ventanas/funciones de la cinta de ApuRisk que se pueden abrir con apurisk_open_window."""
    return automation.ribbon_commands(excel.runner(excel.select_app(instance)))


@mcp.tool()
def apurisk_open_window(name: str, instance: int | None = None) -> str:
    """Abre una ventana o función de la cinta de ApuRisk (por ejemplo «RegistroRiesgos», «BowTie», «VerHeatMap», «Simular»). Ver apurisk_list_windows."""
    return automation.run_ribbon(excel.runner(excel.select_app(instance)), name)


@mcp.tool()
def apurisk_create_register(instance: int | None = None) -> dict[str, Any]:
    """Crea las tablas del Registro de riesgos en el libro activo si faltan. Falla indicando qué requisito falta (por ejemplo, el perfil de criterios sin confirmar)."""
    _, run, scope = _context(instance)
    return risks.create_register(run, scope)


@mcp.tool()
def apurisk_list_risks(status: str | None = None, instance: int | None = None) -> list[dict[str, Any]]:
    """Riesgos del Registro del libro activo (resumen). Filtra por estado: draft, identified, evaluating, treating, monitoring, closed, archived."""
    _, run, scope = _context(instance)
    return risks.list_risks(run, scope, status)


@mcp.tool()
def apurisk_get_risk(risk_id: str, instance: int | None = None) -> dict[str, Any]:
    """Una fila completa del Registro (todas las columnas, validación y transiciones permitidas)."""
    _, run, scope = _context(instance)
    return risks.get_risk(run, scope, risk_id)


@mcp.tool()
def apurisk_create_risk(
    risk_name: str,
    risk_type: str = "Threat",
    event: str | None = None,
    cause: str | None = None,
    consequence: str | None = None,
    category: str | None = None,
    identified_date: str | None = None,
    risk_owner_id: str | None = None,
    wbs_id: str | None = None,
    rbs_id: str | None = None,
    publish: bool = False,
    instance: int | None = None,
) -> dict[str, Any]:
    """Registra un riesgo en la tabla del Registro de ApuRisk del libro activo.

    risk_type: Threat (amenaza), Opportunity (oportunidad) o Issue (problema ya materializado). identified_date: AAAA-MM-DD.
    Se crea en borrador; con publish=true pasa a «identified» si está completo. El ID (R-001...) lo asigna ApuRisk.
    """
    _, run, scope = _context(instance)
    fields = {
        "RiskName": risk_name, "RiskType": risk_type, "Event": event, "Cause": cause, "Consequence": consequence,
        "Category": category, "IdentifiedDate": identified_date, "RiskOwnerId": risk_owner_id, "WbsId": wbs_id, "RbsId": rbs_id,
    }
    return risks.create_risk(run, scope, fields, publish)


@mcp.tool()
def apurisk_update_risk(risk_id: str, fields: dict[str, str], instance: int | None = None) -> dict[str, Any]:
    """Cambia campos editables de un riesgo: RiskName, RiskType, Cause, Event, Consequence, Category, SourceType, SourceDetail, IdentifiedDate, ExposureStart, ExposureEnd, WbsId, RbsId, RiskOwnerId. Todo como texto."""
    _, run, scope = _context(instance)
    return risks.update_risk(run, scope, risk_id, fields)


@mcp.tool()
def apurisk_set_risk_status(risk_id: str, to_status: str, reason: str | None = None, instance: int | None = None) -> dict[str, Any]:
    """Cambia el estado de un riesgo (por ejemplo draft → identified). ApuRisk valida si la transición es posible y por qué no."""
    _, run, scope = _context(instance)
    return risks.summarize(risks.transition(run, scope, risk_id, to_status, reason))


@mcp.tool()
def apurisk_select_risk(risk_id: str, show: str | None = None, instance: int | None = None) -> str:
    """Abre el Registro de riesgos en Excel y deja SELECCIONADO el riesgo, para que la persona lo vea en pantalla.

    show: vacío (solo seleccionarlo), «bowtie» (abre además su BowTie) o «evaluate» (abre además su Evaluación).
    """
    _, run, scope = _context(instance)
    risks.get_risk(run, scope, risk_id)  # falla con claridad si el riesgo no existe
    payload: dict[str, Any] = {"workbookScopeId": scope, "riskId": risk_id}
    if show:
        payload["tool"] = show
    automation.bridge(run, "riskRegister.openRisk", payload)
    return f"{risk_id} seleccionado en el Registro" + (f" ({show})" if show else "")


@mcp.tool()
def apurisk_refresh_windows(instance: int | None = None) -> list[str]:
    """Pide a las ventanas abiertas de ApuRisk (Registro, BowTie, Matriz...) que vuelvan a leer el libro. Las herramientas que cambian datos ya lo hacen solas; úsalo si la persona editó Excel a mano."""
    return automation.refresh_windows(excel.runner(excel.select_app(instance)))


@mcp.tool()
def apurisk_windows(instance: int | None = None) -> list[str]:
    """Ventanas de ApuRisk abiertas ahora mismo («registro», «matriz», «capex»...)."""
    return automation.open_windows(excel.runner(excel.select_app(instance)))


@mcp.tool()
def apurisk_bowtie_get(risk_id: str, instance: int | None = None) -> dict[str, Any]:
    """El BowTie de un riesgo (peligro, evento tope, causas, consecuencias y barreras) o un aviso si todavía no tiene."""
    _, run, scope = _context(instance)
    diagram = bowtie.load(run, scope, risk_id)
    return bowtie.summarize(diagram) if diagram else {"riskId": risk_id, "bowTie": None, "message": "Este riesgo todavía no tiene BowTie."}


@mcp.tool()
def apurisk_bowtie_edit(
    risk_id: str,
    hazard_name: str | None = None,
    hazard_description: str | None = None,
    top_event: str | None = None,
    threats: list[dict[str, Any]] | None = None,
    consequences: list[dict[str, Any]] | None = None,
    barriers: list[dict[str, Any]] | None = None,
    show: bool = True,
    instance: int | None = None,
) -> dict[str, Any]:
    """Agrega o cambia cosas en el BowTie de un riesgo (lo crea si no existe) y lo muestra en Excel.

    Solo AGREGA causas/consecuencias/barreras y cambia peligro y evento tope; no borra ni reordena.
    - threats / consequences: lista de {name, description?, probability_pct? (0-100), barriers?: [{name, description?, owner_id?}]}
    - barriers (sobre ramas que ya existen o se agregan en esta llamada): lista de {side: "threat"|"consequence", branch: nombre o Id, name, description?, owner_id?}
    show=true abre el BowTie de ese riesgo en la ventana de Excel; si ya estaba abierto, se actualiza solo.
    """
    _, run, scope = _context(instance)
    risks.get_risk(run, scope, risk_id)
    result = bowtie.edit(run, scope, risk_id, hazard_name=hazard_name, hazard_description=hazard_description, top_event=top_event,
                         threats=threats, consequences=consequences, barriers=barriers)
    if show:
        automation.bridge(run, "riskRegister.openRisk", {"workbookScopeId": scope, "riskId": risk_id, "tool": "bowtie"})
    return result


def _matrix(run: automation.Runner, commands: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Abre (o trae al frente) la Matriz de riesgos del libro activo y le envía los comandos; esperan a que la página termine de cargar."""
    automation.run_ribbon(run, "VerHeatMap")
    for command, payload in commands:
        automation.ui_command(run, "matriz", command, payload)
    return {"window": "matriz", "applied": [command for command, _ in commands]}


@mcp.tool()
def apurisk_matrix_view(
    profile: str | None = None,
    scenario: str | None = None,
    perspective: str | None = None,
    search: str | None = None,
    show_outside: bool | None = None,
    show_outdated: bool | None = None,
    show_drafts: bool | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
    clear_filters: bool = False,
    instance: int | None = None,
) -> dict[str, Any]:
    """Abre la Matriz de riesgos y cambia lo que muestra, como si se pulsaran sus botones.

    profile: «Threats» (amenazas) u «Opportunities» (oportunidades). scenario/perspective: nombre o id (por ejemplo «Residual», «Inherente»).
    search: texto del buscador. show_outside / show_outdated / show_drafts: activa o desactiva los filtros rápidos (fuera de tolerancia,
    desactualizadas, borradores). sort_by: top, priority, id, name, probability, impact, category, review o validity; sort_direction: asc o desc.
    clear_filters=true restablece los filtros antes de aplicar lo demás.
    """
    run = excel.runner(excel.select_app(instance))
    commands: list[tuple[str, dict[str, Any]]] = []
    if clear_filters:
        commands.append(("clearFilters", {}))
    if profile:
        commands.append(("setProfile", {"profile": profile}))
    if scenario:
        commands.append(("setScenario", {"scenario": scenario}))
    if perspective:
        commands.append(("setPerspective", {"perspective": perspective}))
    for key, value in (("outside", show_outside), ("outdated", show_outdated), ("draft", show_drafts)):
        if value is not None:
            commands.append(("setFilter", {"key": key, "on": value}))
    if search is not None:
        commands.append(("search", {"text": search}))
    if sort_by:
        commands.append(("sortBy", {"key": sort_by, "direction": sort_direction}))
    return _matrix(run, commands)


@mcp.tool()
def apurisk_matrix_select(
    risk_id: str | None = None,
    probability: int | None = None,
    impact: int | None = None,
    clear: bool = False,
    open_evaluation: bool = False,
    instance: int | None = None,
) -> dict[str, Any]:
    """En la Matriz de riesgos: selecciona un riesgo (risk_id) o una celda (probability e impact, como números de la escala), o quita la selección (clear=true). Con open_evaluation=true abre además la Evaluación de ese riesgo."""
    run = excel.runner(excel.select_app(instance))
    commands: list[tuple[str, dict[str, Any]]] = []
    if clear:
        commands += [("selectCell", {"probabilityScore": None, "impactLevel": None}), ("selectRisk", {"riskId": None})]
    if probability is not None and impact is not None:
        commands.append(("selectCell", {"probabilityScore": probability, "impactLevel": impact}))
    elif probability is not None or impact is not None:
        raise ApuriskError("invalid_field", "Para seleccionar una celda indica probability e impact.")
    if risk_id:
        commands.append(("selectRisk", {"riskId": risk_id}))
        if open_evaluation:
            commands.append(("openEvaluation", {"riskId": risk_id}))
    if not commands:
        raise ApuriskError("invalid_field", "Indica risk_id, probability e impact, o clear=true.")
    return _matrix(run, commands)


@mcp.tool()
def apurisk_risk_health(stale_days: int = 30, priority_only: bool = False, today: str | None = None, instance: int | None = None) -> dict[str, Any]:
    """Riesgos con información incompleta, sin responsable, con evaluación pendiente o sin actualizar hace más de «stale_days» días.

    Devuelve, por riesgo, su nivel, responsable (con nombre), campos faltantes, última actividad y los problemas. «priority_only» deja solo los prioritarios
    (nivel Extremo, Alto o Prioritaria). «today» (AAAA-MM-DD) fija la fecha de referencia; por omisión, hoy.
    """
    _, run, scope = _context(instance)
    return analysis.risk_health(run, scope, stale_days=stale_days, priority_only=priority_only, today=today)


@mcp.tool()
def apurisk_risk_changes(scenario: str = "Current", only_changed: bool = True, instance: int | None = None) -> dict[str, Any]:
    """Qué riesgos cambiaron desde la «última revisión» (la revisión confirmada anterior de su evaluación) y qué cambió: nivel, probabilidad o impacto por perspectiva.

    scenario: Current (por omisión), Inherent, Residual o Potential. Incluye el estado actual de los controles (barreras del BowTie) de cada riesgo.
    Los riesgos con una sola revisión se cuentan en «sinRevisionAnterior»: no hay con qué comparar.
    """
    _, run, scope = _context(instance)
    return analysis.risk_changes(run, scope, scenario=scenario, only_changed=only_changed)


@mcp.tool()
def apurisk_actions_due(days: int = 7, today: str | None = None, instance: int | None = None) -> dict[str, Any]:
    """Acciones de respuesta abiertas que están vencidas o vencen en los próximos «days» días, con el riesgo asociado, el responsable (con nombre) y la fecha."""
    _, run, scope = _context(instance)
    return analysis.actions_due(run, scope, days=days, today=today)


@mcp.tool()
def apurisk_risk_dossier(risk_id: str, today: str | None = None, instance: int | None = None) -> dict[str, Any]:
    """Ficha completa de UN riesgo: datos, nivel por escenario, qué cambió desde la última revisión, controles, acciones abiertas, cuantificación,
    y «informacionFaltante»: lo que falta en ApuRisk para sustentar una decisión sobre ese riesgo. Úsala antes de recomendar algo."""
    _, run, scope = _context(instance)
    return analysis.risk_dossier(run, scope, risk_id, today=today)


@mcp.tool()
def apurisk_bridge(type: str, payload: dict[str, Any] | None = None, instance: int | None = None) -> Any:
    """Comando avanzado del puente de ApuRisk (los mismos que usan sus ventanas), por ejemplo «riskEvaluation.overview» o «riskActions.list». «workbookScopeId» se completa solo si falta."""
    _, run, scope = _context(instance)
    body = {"workbookScopeId": scope, **(payload or {})}
    return automation.bridge(run, type, body)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
