"""Servidor MCP (stdio). Cada herramienta es una acción concreta sobre Excel o ApuRisk; todo lo demás lo decide el add-in."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import automation, excel, install_check, risks
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
def apurisk_bridge(type: str, payload: dict[str, Any] | None = None, instance: int | None = None) -> Any:
    """Comando avanzado del puente de ApuRisk (los mismos que usan sus ventanas), por ejemplo «riskEvaluation.overview» o «riskActions.list». «workbookScopeId» se completa solo si falta."""
    _, run, scope = _context(instance)
    body = {"workbookScopeId": scope, **(payload or {})}
    return automation.bridge(run, type, body)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
