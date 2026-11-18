"""Operaciones sobre el Registro de riesgos, siempre a través del puente del add-in (sus validaciones, IDs y protección de hojas)."""

from __future__ import annotations

from typing import Any

from . import automation
from .automation import ApuriskError, Runner

#: Columnas del maestro que una persona puede editar (entrada + referencias). El resto lo calcula ApuRisk.
EDITABLE_FIELDS = (
    "RiskName", "RiskType", "Cause", "Event", "Consequence", "Category", "SourceType", "SourceDetail",
    "IdentifiedDate", "ExposureStart", "ExposureEnd", "WbsId", "RbsId", "RiskOwnerId",
)
RISK_TYPES = ("Threat", "Opportunity", "Issue")
STATUSES = ("draft", "identified", "evaluating", "treating", "monitoring", "closed", "archived")

#: Columnas que se muestran en los listados (el maestro completo tiene 38).
SUMMARY_FIELDS = (
    "RiskName", "RiskType", "Event", "Cause", "Consequence", "Category", "RiskOwnerId", "IdentifiedDate",
    "Current.MatrixLevel", "Current.AppetiteStatus", "Current.EvaluationStatus",
)


def check_fields(fields: dict[str, Any]) -> dict[str, str]:
    """Valida los campos a escribir: solo columnas editables y siempre texto (las celdas del Registro son texto canónico)."""
    clean: dict[str, str] = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise ApuriskError("invalid_field", f"«{key}» no es editable. Campos permitidos: {', '.join(EDITABLE_FIELDS)}.")
        if value is None:
            continue
        clean[key] = str(value)
    risk_type = clean.get("RiskType")
    if risk_type is not None and risk_type not in RISK_TYPES:
        raise ApuriskError("invalid_field", f"RiskType debe ser uno de {', '.join(RISK_TYPES)}.")
    return clean


def summarize(row: dict[str, Any]) -> dict[str, Any]:
    cells = row.get("cells") or {}
    validation = row.get("validation") or {}
    return {
        "riskId": row.get("riskId"),
        "status": row.get("status"),
        **{key: cells[key] for key in SUMMARY_FIELDS if cells.get(key)},
        "completeness": validation.get("completeness"),
        "missingRequired": validation.get("missingRequired") or [],
        "allowedTransitions": row.get("allowedTransitions") or [],
    }


def load(run: Runner, scope: str) -> dict[str, Any]:
    snapshot = automation.bridge(run, "riskRegister.list", {"workbookScopeId": scope})
    if not snapshot.get("tablesExist"):
        raise ApuriskError(
            "register_missing",
            "Este libro todavía no tiene el Registro de riesgos. Créalo con apurisk_create_register o desde la cinta (Identificar → Registro de riesgos).",
        )
    return snapshot


def list_risks(run: Runner, scope: str, status: str | None = None) -> list[dict[str, Any]]:
    rows = load(run, scope)["rows"]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return [summarize(row) for row in rows]


def get_risk(run: Runner, scope: str, risk_id: str) -> dict[str, Any]:
    for row in load(run, scope)["rows"]:
        if row.get("riskId") == risk_id:
            return row
    raise ApuriskError("not_found", f"No existe el riesgo {risk_id} en el Registro.")


def create_register(run: Runner, scope: str) -> dict[str, Any]:
    """Crea las tablas del Registro si faltan (puede fallar con el motivo del preflight: perfil sin confirmar, etc.)."""
    preflight = automation.bridge(run, "riskRegister.preflight", {"workbookScopeId": scope})
    if not preflight.get("canCreateRegister"):
        pending = [check.get("message") or check.get("title") for check in preflight.get("checks", []) if check.get("state") != "ready"]
        raise ApuriskError("prerequisites_missing", "Faltan requisitos para crear el Registro.", pending)
    snapshot = automation.bridge(run, "riskRegister.ensure", {"workbookScopeId": scope})
    return {"tablesExist": snapshot.get("tablesExist"), "risks": len(snapshot.get("rows", []))}


def create_risk(run: Runner, scope: str, fields: dict[str, Any], publish: bool = False) -> dict[str, Any]:
    """Crea un riesgo en borrador, le escribe los campos y, si se pide, lo publica como «identified»."""
    changes = check_fields(fields)
    load(run, scope)  # comprueba que el Registro exista antes de crear nada
    row = automation.bridge(run, "riskRegister.createDraft", {"workbookScopeId": scope})
    if not row.get("riskId"):
        raise ApuriskError("create_failed", "ApuRisk no devolvió el riesgo nuevo; revisa el Registro antes de reintentar.")
    if changes:
        row = _update(run, scope, row["riskId"], row["fingerprint"], changes)
    if publish:
        row = transition(run, scope, row["riskId"], "identified", row=row)
    return summarize(row)


def _update(run: Runner, scope: str, risk_id: str, fingerprint: str, changes: dict[str, str]) -> dict[str, Any]:
    """updateFields, transition y createDraft responden con la fila ya cambiada (no con todo el Registro)."""
    return automation.bridge(run, "riskRegister.updateFields", {
        "workbookScopeId": scope, "riskId": risk_id, "fingerprint": fingerprint, "changes": changes,
    })


def update_risk(run: Runner, scope: str, risk_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    changes = check_fields(fields)
    if not changes:
        raise ApuriskError("invalid_field", "No hay campos que cambiar.")
    row = get_risk(run, scope, risk_id)
    return summarize(_update(run, scope, risk_id, row["fingerprint"], changes))


def transition(run: Runner, scope: str, risk_id: str, to_status: str, reason: str | None = None, row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cambia el estado de un riesgo (por ejemplo ``draft`` → ``identified``). El add-in valida si la transición es posible."""
    if to_status not in STATUSES:
        raise ApuriskError("invalid_status", f"Estado desconocido «{to_status}». Estados: {', '.join(STATUSES)}.")
    current = row or get_risk(run, scope, risk_id)
    return automation.bridge(run, "riskRegister.transition", {
        "workbookScopeId": scope, "riskId": risk_id, "fingerprint": current["fingerprint"], "toStatus": to_status, "reason": reason,
    })
