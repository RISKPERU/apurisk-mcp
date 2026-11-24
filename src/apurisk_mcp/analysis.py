"""Consultas de análisis sobre el libro: salud del Registro, cambios entre revisiones, acciones por vencer y ficha de un riesgo.

Todo se calcula con los comandos de lectura del puente de ApuRisk (los mismos que usan sus ventanas); nada se escribe. Cada resultado dice con qué
datos se calculó y qué falta, para que quien lo use no tenga que suponer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import automation
from .automation import ApuriskError, Runner

#: Niveles que cuentan como «prioritarios» (amenazas e issues Extremo/Alto; oportunidades Prioritarias).
PRIORITY_LEVELS = ("Extremo", "Alto", "Prioritaria")
DONE_STATUSES = ("done", "completed", "cancelled")
ACTION_STATUS_LABEL = {"planned": "planificada", "in_progress": "en curso", "done": "hecha", "completed": "hecha", "cancelled": "cancelada"}
SCENARIOS = ("Inherent", "Current", "Residual", "Potential")


def _day(value: Any) -> date | None:
    """Fecha (sin hora) de un texto «2026-11-13» o «2026-11-13T03:56:22Z»; None si no es una fecha."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _today(today: date | str | None) -> date:
    if isinstance(today, str):
        parsed = _day(today)
        if parsed is None:
            raise ApuriskError("invalid_field", "today debe ser una fecha AAAA-MM-DD.")
        return parsed
    return today or date.today()


def members(run: Runner, scope: str) -> dict[str, str]:
    """Id → nombre de las personas del proyecto (los responsables se guardan como «m1», «m2»…)."""
    try:
        data = automation.bridge(run, "controls.load", {"workbookScopeId": scope})
        return {str(item["id"]): str(item["name"]) for item in data.get("reviewers", []) if item.get("id")}
    except (ApuriskError, KeyError, TypeError):
        return {}


def _who(owner_id: str | None, names: dict[str, str]) -> dict[str, Any]:
    return {"id": owner_id or None, "nombre": names.get(owner_id or "", None) if owner_id else None}


def _rows(run: Runner, scope: str) -> list[dict[str, Any]]:
    data = automation.bridge(run, "riskRegister.list", {"workbookScopeId": scope})
    if not data.get("tablesExist", True):
        raise ApuriskError("no_register", "El libro todavía no tiene el Registro de riesgos.")
    return list(data.get("rows") or [])


def _level(cells: dict[str, Any]) -> str | None:
    return cells.get("Current.MatrixLevel") or None


def _last_activity(cells: dict[str, Any]) -> date | None:
    """Última vez que se tocó el riesgo: lo más reciente entre su última edición y su última evaluación."""
    days = [d for d in (_day(cells.get("UpdatedAt")), _day(cells.get("Current.EvaluationDate"))) if d]
    return max(days) if days else None


def risk_health(run: Runner, scope: str, stale_days: int = 30, priority_only: bool = False, today: date | str | None = None) -> dict[str, Any]:
    """Riesgos con información incompleta, sin responsable, sin evaluar o sin actualizar hace más de «stale_days» días."""
    now = _today(today)
    names = members(run, scope)
    flagged: list[dict[str, Any]] = []
    total = 0
    for row in _rows(run, scope):
        cells = row.get("cells") or {}
        if row.get("status") in ("closed", "archived"):
            continue
        total += 1
        level = _level(cells)
        priority = level in PRIORITY_LEVELS
        validation = row.get("validation") or {}
        missing = list(validation.get("missingRequired") or [])
        owner = cells.get("RiskOwnerId") or ""
        last = _last_activity(cells)
        days = (now - last).days if last else None
        problems: list[str] = []
        if not owner:
            problems.append("sin responsable")
        if missing or cells.get("CompletenessStatus") not in (None, "", "Completo"):
            problems.append("información incompleta")
        if cells.get("Current.EvaluationStatus") == "pending":
            problems.append("evaluación pendiente")
        if days is not None and days > stale_days:
            problems.append(f"sin actualizar hace {days} días")
        if not problems or (priority_only and not priority):
            continue
        flagged.append({
            "riskId": row.get("riskId"), "nombre": cells.get("RiskName"), "tipo": cells.get("RiskType"), "estado": row.get("status"),
            "nivelActual": level, "prioritario": priority, "responsable": _who(owner, names),
            "camposFaltantes": missing, "ultimaActividad": last.isoformat() if last else None, "diasSinActualizar": days, "problemas": problems,
        })
    flagged.sort(key=lambda item: (not item["prioritario"], -(item["diasSinActualizar"] or 0), item["riskId"] or ""))
    return {
        "fechaReferencia": now.isoformat(), "umbralDiasSinActualizar": stale_days, "riesgosRevisados": total, "conProblemas": len(flagged),
        "prioritariosConProblemas": sum(1 for item in flagged if item["prioritario"]),
        "criterio": "Prioritario = nivel actual Extremo, Alto o Prioritaria. «Última actividad» = lo más reciente entre la última edición del riesgo y su última evaluación.",
        "riesgos": flagged,
    }


def _history(run: Runner, scope: str, risk_id: str, scenario: str) -> list[dict[str, Any]]:
    try:
        items = automation.bridge(run, "riskEvaluation.history", {"workbookScopeId": scope, "riskId": risk_id, "scenario": scenario}) or []
    except ApuriskError:
        return []
    return sorted((item for item in items if item.get("isConfirmed", True)), key=lambda item: int(item.get("revision") or 0))


def _impacts(revision: dict[str, Any]) -> dict[str, int | None]:
    return {item["perspectiveId"]: item.get("impactLevel") for item in revision.get("perspectives") or []}


def compare_revisions(previous: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    """Qué cambió entre dos revisiones confirmadas de una evaluación: nivel, probabilidad e impacto (por perspectiva)."""
    before, after = _impacts(previous), _impacts(latest)
    impact_changes = [
        {"perspectiva": key, "antes": before.get(key), "despues": after.get(key)}
        for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)
    ]
    p0, p1 = previous.get("probabilityPct"), latest.get("probabilityPct")
    v0, v1 = previous.get("consolidatedValue"), latest.get("consolidatedValue")
    direction = "igual"
    if v0 is not None and v1 is not None:
        direction = "subió" if v1 > v0 else "bajó" if v1 < v0 else "igual"
    elif previous.get("consolidatedLevelName") != latest.get("consolidatedLevelName"):
        direction = "cambió"
    return {
        "nivel": {"antes": previous.get("consolidatedLevelName"), "despues": latest.get("consolidatedLevelName"), "variacion": direction},
        "probabilidad": {"antes": p0, "despues": p1, "cambio": p0 != p1},
        "impacto": {"cambio": bool(impact_changes), "perspectivas": impact_changes},
        "revision": {"anterior": previous.get("revision"), "actual": latest.get("revision")},
        "fechaRevisionAnterior": previous.get("evaluationDate"), "fechaRevisionActual": latest.get("evaluationDate"),
        "motivoActual": latest.get("basis"),
    }


def _controls_by_risk(run: Runner, scope: str) -> dict[str, dict[str, Any]]:
    try:
        data = automation.bridge(run, "controls.load", {"workbookScopeId": scope})
    except ApuriskError:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for risk in data.get("risks", []):
        counts: dict[str, int] = {}
        for barrier in risk.get("barriers") or []:
            counts[barrier.get("status") or "?"] = counts.get(barrier.get("status") or "?", 0) + 1
        result[risk["id"]] = {"barreras": len(risk.get("barriers") or []), "porEstado": counts}
    return result


def risk_changes(run: Runner, scope: str, scenario: str = "Current", only_changed: bool = True) -> dict[str, Any]:
    """Riesgos cuya evaluación tiene una revisión posterior a la «última revisión» (la revisión confirmada anterior) y qué cambió."""
    if scenario not in SCENARIOS:
        raise ApuriskError("invalid_field", f"scenario debe ser uno de {', '.join(SCENARIOS)}.")
    controls = _controls_by_risk(run, scope)
    changed: list[dict[str, Any]] = []
    no_baseline = 0
    examined = 0
    for row in _rows(run, scope):
        cells = row.get("cells") or {}
        if row.get("status") in ("closed", "archived", "draft"):
            continue
        history = _history(run, scope, row["riskId"], scenario)
        if not history:
            continue
        examined += 1
        if len(history) < 2:
            no_baseline += 1
            continue
        diff = compare_revisions(history[-2], history[-1])
        moved = diff["nivel"]["variacion"] != "igual" or diff["probabilidad"]["cambio"] or diff["impacto"]["cambio"]
        if only_changed and not moved:
            continue
        changed.append({"riskId": row["riskId"], "nombre": cells.get("RiskName"), "nivelActual": _level(cells), **diff, "controles": controls.get(row["riskId"])})
    order = {"subió": 0, "cambió": 1, "bajó": 2, "igual": 3}
    changed.sort(key=lambda item: (order.get(item["nivel"]["variacion"], 9), item["riskId"]))
    return {
        "escenario": scenario, "riesgosEvaluados": examined, "sinRevisionAnterior": no_baseline,
        "subieronDeNivel": sum(1 for item in changed if item["nivel"]["variacion"] == "subió"), "conCambios": len(changed),
        "criterio": "«Última revisión» = la revisión confirmada anterior de la evaluación del escenario. Controles: estado actual de las barreras del BowTie; "
                    "el historial de revisiones de controles no se compara aquí.",
        "riesgos": changed,
    }


def actions_due(run: Runner, scope: str, days: int = 7, today: date | str | None = None) -> dict[str, Any]:
    """Acciones abiertas vencidas o que vencen en los próximos «days» días, con su riesgo, responsable y fecha."""
    now = _today(today)
    limit = now + timedelta(days=days)
    names = members(run, scope)
    risks = {row["riskId"]: (row.get("cells") or {}) for row in _rows(run, scope)}
    actions = automation.bridge(run, "riskActions.list", {"workbookScopeId": scope}) or []
    overdue: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for action in actions:
        if action.get("status") in DONE_STATUSES:
            continue
        due = _day(action.get("dueDate"))
        if due is None or due > limit:
            continue
        cells = risks.get(action.get("riskId"), {})
        item = {
            "actionId": action.get("actionId"), "riskId": action.get("riskId"), "riesgo": cells.get("RiskName"), "nivelRiesgo": _level(cells),
            "accion": action.get("description"), "tipo": action.get("actionType"), "responsable": _who(action.get("ownerId"), names),
            "fechaLimite": due.isoformat(), "estado": ACTION_STATUS_LABEL.get(action.get("status"), action.get("status")), "avancePct": action.get("progressPct") or None,
        }
        if due < now:
            overdue.append({**item, "diasVencida": (now - due).days})
        else:
            upcoming.append({**item, "diasParaVencer": (due - now).days})
    overdue.sort(key=lambda item: -item["diasVencida"])
    upcoming.sort(key=lambda item: item["diasParaVencer"])
    return {
        "fechaReferencia": now.isoformat(), "ventanaDias": days, "vencidas": overdue, "porVencer": upcoming,
        "totalAccionesRevisadas": len(actions), "criterio": "Solo acciones no hechas ni canceladas, con fecha límite.",
    }


def _latest(run: Runner, scope: str, risk_id: str, scenario: str) -> dict[str, Any] | None:
    history = _history(run, scope, risk_id, scenario)
    return history[-1] if history else None


def _quantification(run: Runner, scope: str, risk_id: str) -> dict[str, Any] | None:
    try:
        summaries = automation.bridge(run, "bowTie.list", {"workbookScopeId": scope, "riskId": risk_id}) or []
        if not summaries:
            return None
        diagram = automation.bridge(run, "bowTie.get", {"workbookScopeId": scope, "bowTieId": summaries[0]["id"]}) or {}
        q = diagram.get("Quantification") or {}
        return {"costo": q.get("Cost") if q.get("IncludeCost") else None, "plazo": q.get("Schedule") if q.get("IncludeSchedule") else None}
    except ApuriskError:
        return None


def risk_dossier(run: Runner, scope: str, risk_id: str, today: date | str | None = None) -> dict[str, Any]:
    """Ficha completa de un riesgo y la lista de información que falta para sustentar una decisión sobre él."""
    now = _today(today)
    names = members(run, scope)
    row = next((item for item in _rows(run, scope) if item.get("riskId") == risk_id), None)
    if row is None:
        raise ApuriskError("risk_not_found", f"No existe el riesgo {risk_id}.")
    cells = row.get("cells") or {}
    validation = row.get("validation") or {}
    scenarios: dict[str, Any] = {}
    for scenario in SCENARIOS:
        latest = _latest(run, scope, risk_id, scenario)
        if latest:
            scenarios[scenario] = {"nivel": latest.get("consolidatedLevelName"), "probabilidadPct": latest.get("probabilityPct"), "fecha": latest.get("evaluationDate"), "revision": latest.get("revision")}
    change = None
    current_history = _history(run, scope, risk_id, "Current")
    if len(current_history) >= 2:
        change = compare_revisions(current_history[-2], current_history[-1])
    all_actions = [a for a in (automation.bridge(run, "riskActions.list", {"workbookScopeId": scope, "riskId": risk_id}) or []) if a.get("riskId") == risk_id]
    open_actions = [a for a in all_actions if a.get("status") not in DONE_STATUSES]
    action_items = []
    for action in open_actions:
        due = _day(action.get("dueDate"))
        action_items.append({
            "actionId": action.get("actionId"), "accion": action.get("description"), "tipo": action.get("actionType"), "responsable": _who(action.get("ownerId"), names),
            "fechaLimite": due.isoformat() if due else None, "estado": ACTION_STATUS_LABEL.get(action.get("status"), action.get("status")), "avancePct": action.get("progressPct") or None,
            "vencida": bool(due and due < now), "diasParaVencer": (due - now).days if due else None,
        })
    action_items.sort(key=lambda item: (item["fechaLimite"] is None, item["fechaLimite"] or ""))
    controls = _controls_by_risk(run, scope).get(risk_id)
    quant = _quantification(run, scope, risk_id)
    last = _last_activity(cells)

    gaps: list[str] = []
    if not cells.get("RiskOwnerId"):
        gaps.append("El riesgo no tiene responsable asignado.")
    if validation.get("missingRequired"):
        gaps.append("Campos obligatorios sin completar: " + ", ".join(validation["missingRequired"]) + ".")
    if cells.get("Current.EvaluationStatus") == "pending" or "Current" not in scenarios:
        gaps.append("No hay una evaluación Actual confirmada.")
    if cells.get("RiskType") != "Opportunity" and "Residual" not in scenarios:
        gaps.append("No tiene evaluación Residual: no se puede decir cuánto baja el riesgo con las acciones.")
    if len(current_history) < 2:
        gaps.append("Solo hay una revisión de la evaluación Actual: no se puede decir qué cambió desde la última revisión.")
    if last and (now - last).days > 30:
        gaps.append(f"Lleva {(now - last).days} días sin actualizarse.")
    if quant is None or (quant["costo"] is None and quant["plazo"] is None):
        gaps.append("No tiene cuantificación de costo ni de plazo (no entra a la simulación).")
    elif quant["costo"] is None or quant["plazo"] is None:
        gaps.append("Solo está cuantificado " + ("el costo" if quant["costo"] else "el plazo") + ".")
    if controls and controls["porEstado"].get("Proposed"):
        gaps.append(f"{controls['porEstado']['Proposed']} control(es) siguen solo propuestos, sin implementar.")
    if controls and controls["porEstado"].get("Partial"):
        gaps.append(f"{controls['porEstado']['Partial']} control(es) están implementados solo en parte.")
    if not open_actions:
        gaps.append("No tiene acciones de respuesta abiertas.")
    if open_actions and all(not a.get("progressPct") for a in open_actions):
        gaps.append("Ninguna acción abierta tiene avance registrado.")
    overdue = [a for a in action_items if a["vencida"]]
    if overdue:
        gaps.append(f"{len(overdue)} acción(es) vencida(s).")
    if all_actions and not any(a.get("effectiveness") for a in all_actions):
        pass  # la efectividad no viaja en este listado: no se afirma nada
    return {
        "riskId": risk_id, "nombre": cells.get("RiskName"), "tipo": cells.get("RiskType"), "estado": row.get("status"),
        "evento": cells.get("Event"), "causa": cells.get("Cause"), "consecuencia": cells.get("Consequence"),
        "responsable": _who(cells.get("RiskOwnerId"), names), "nivelActual": _level(cells), "escenarios": scenarios, "cambioDesdeUltimaRevision": change,
        "controles": controls, "accionesAbiertas": action_items, "cuantificacion": quant, "ultimaActividad": last.isoformat() if last else None,
        "informacionFaltante": gaps, "fechaReferencia": now.isoformat(),
    }
