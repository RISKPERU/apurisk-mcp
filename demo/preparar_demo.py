"""Prepara el libro «Apurisk - Proyecto Demo» para la demostración con Claude.

Deja en el libro lo que las seis preguntas necesitan encontrar: riesgos prioritarios con problemas, una segunda revisión de varias evaluaciones, acciones
vencidas y por vencer, evaluaciones residuales (escenario mitigado).

Las escrituras pasan por el add-in (validaciones, IDs, historial) siempre que se puede; solo se escriben celdas a mano para ANTIGUAR fechas
(el add-in no deja retroceder la fecha de una evaluación).

Uso (con Excel cerrado o con el libro de trabajo abierto en el Excel donde está cargado ApuRisk):
    python demo/preparar_demo.py "C:\\ruta\\demo-trabajo.xlsx" --hoy 2026-11-20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import date, timedelta
from typing import Any

from apurisk_mcp import analysis, automation, excel, risks

OWNER_FALLBACK = "m1"


def log(text: str) -> None:
    print(text, flush=True)


class Demo:
    def __init__(self, app: Any, today: date) -> None:
        self.app, self.today = app, today
        self.run = excel.runner(app)
        self.scope = automation.status(self.run)["workbookScopeId"]

    def b(self, kind: str, payload: dict[str, Any] | None = None) -> Any:
        return automation.bridge(self.run, kind, {"workbookScopeId": self.scope, **(payload or {})})

    # ───────────── Evaluaciones ─────────────
    def evaluate(self, risk_id: str, scenario: str, probability: float | None = None, impact_delta: dict[str, int] | None = None,
                 impacts: dict[str, int] | None = None, basis: str = "", evaluator: str | None = None) -> dict[str, Any]:
        """Crea y confirma una revisión nueva de la evaluación (usa la vigente como base)."""
        summary = self.b("riskEvaluation.get", {"riskId": risk_id, "scenario": scenario})
        base = summary.get("confirmed") or {}
        levels = dict(impacts) if impacts else {p["perspectiveId"]: p["impactLevel"] for p in base.get("perspectives", [])}
        for perspective, delta in (impact_delta or {}).items():
            if perspective in levels and levels[perspective] is not None:
                levels[perspective] = max(1, min(5, levels[perspective] + delta))
        body = {
            "riskId": risk_id, "scenario": scenario, "probabilityPct": probability if probability is not None else base.get("probabilityPct"),
            "impacts": levels, "evaluatorId": evaluator or base.get("evaluatorId") or OWNER_FALLBACK, "basis": basis or base.get("basis") or "Revisión del equipo.",
            "clientOperationId": uuid.uuid4().hex,
        }
        self.b("riskEvaluation.saveDraft", body)
        done = self.b("riskEvaluation.confirm", body)
        return done.get("confirmed") or {}

    def current(self, risk_id: str, scenario: str = "Current") -> dict[str, Any]:
        return (self.b("riskEvaluation.get", {"riskId": risk_id, "scenario": scenario}).get("confirmed")) or {}

    def revise(self, risk_id: str, label: str, **kwargs: Any) -> None:
        before = self.current(risk_id)
        after = self.evaluate(risk_id, "Current", **kwargs)
        log(f"  {risk_id} {label}: {before.get('consolidatedLevelName')} P{before.get('probabilityPct')} -> {after.get('consolidatedLevelName')} P{after.get('probabilityPct')}")

    # ───────────── Acciones ─────────────
    def set_action(self, action: dict[str, Any], due: date, status: str | None = None, progress: str | None = None, note: str | None = None) -> None:
        start = date.fromisoformat(action["startDate"]) if action.get("startDate") else None
        new_start = min(start, due - timedelta(days=10)) if start else due - timedelta(days=30)
        body = {
            "riskId": action["riskId"], "actionId": action["actionId"], "actionType": action["actionType"], "description": action["description"],
            "ownerId": action["ownerId"], "startDate": new_start.isoformat(), "dueDate": due.isoformat(), "status": status or action["status"],
            "progressPct": progress if progress is not None else action.get("progressPct") or "", "notes": note if note is not None else action.get("notes") or "",
            "reopenReason": "", "requireMinimumFields": False,
        }
        self.b("riskActions.save", body)

    # ───────────── Celdas a mano (solo para antiguar fechas) ─────────────
    def table(self, name: str) -> Any:
        for sheet in self.app.ActiveWorkbook.Worksheets:
            for lo in sheet.ListObjects:
                if lo.Name == name:
                    try:
                        sheet.Unprotect()          # el add-in protege sus hojas; sin contraseña, y solo en esta copia de trabajo
                    except Exception:  # noqa: BLE001
                        pass
                    return lo
        raise RuntimeError(f"No encuentro la tabla {name}.")

    def write_text(self, table: str, key_column: str, key: str, values: dict[str, str]) -> int:
        """Escribe texto en columnas de las filas cuya columna clave vale «key». Devuelve cuántas filas tocó."""
        lo = self.table(table)
        header = [str(c.Value2) for c in lo.HeaderRowRange.Cells]
        key_index = header.index(key_column) + 1
        touched = 0
        for row in lo.ListRows:
            cells = row.Range
            if str(cells.Cells(1, key_index).Value2) == key:
                for column, text in values.items():
                    cell = cells.Cells(1, header.index(column) + 1)
                    cell.NumberFormat = "@"
                    cell.Value2 = text
                touched += 1
        return touched

    def age_risk(self, risk_id: str, days_ago: int) -> None:
        """Hace que el riesgo parezca sin tocar desde hace «days_ago» días (edición y evaluaciones)."""
        day = (self.today - timedelta(days=days_ago)).isoformat()
        self.write_text("RiskMasterTable", "RiskId", risk_id, {"UpdatedAt": f"{day}T14:00:00Z", "Current.EvaluationDate": day})
        lo = self.table("RiskEvaluations")
        header = [str(c.Value2) for c in lo.HeaderRowRange.Cells]
        rid, date_col, conf_col, scen = header.index("RiskId") + 1, header.index("EvaluationDate") + 1, header.index("ConfirmedAt") + 1, header.index("ScenarioKey") + 1
        for row in lo.ListRows:
            cells = row.Range
            if str(cells.Cells(1, rid).Value2) == risk_id:
                for col, text in ((date_col, day), (conf_col, f"{day}T14:00:00Z")):
                    cells.Cells(1, col).NumberFormat = "@"
                    cells.Cells(1, col).Value2 = text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("libro")
    parser.add_argument("--hoy", default=date.today().isoformat(), help="Fecha de la demostración (AAAA-MM-DD); las fechas relativas se calculan desde ella.")
    parser.add_argument("--xll", default=r"C:\System\Work\RiskPerú\apurisk-addin\artifacts\Apurisk.ExcelAddIn64-packed.xll")
    args = parser.parse_args()
    today = date.fromisoformat(args.hoy)

    app, _ = excel.open_workbook(args.libro)
    try:
        automation.status(excel.runner(app))
    except automation.ApuriskError:
        excel.load_addin(app, args.xll)
        time.sleep(4)
    demo = Demo(app, today)

    log("1) Segunda revisión de evaluaciones (qué subió, qué bajó, qué no cambió)")
    demo.revise("R-005", "interferencias: más probable y más impacto en plazo", probability=55, impact_delta={"schedule": 1}, basis="Revisión semanal: dos disciplinas siguen sin resolver las interferencias del modelo.")
    demo.revise("R-002", "acero: sube la probabilidad", probability=60, basis="Cotizaciones recientes muestran una nueva alza del acero estructural.")
    demo.revise("R-031", "contratista de montaje: peor impacto en plazo", impact_delta={"schedule": 1, "financial": 1}, basis="El contratista informó 3 semanas de atraso acumulado.")
    demo.revise("R-004", "comunidad: sube la probabilidad", probability=85, basis="La comunidad anunció un paro para la próxima semana.")
    demo.revise("R-028", "tránsito: baja la probabilidad", probability=3, basis="Se implementó el plan de transporte con escoltas.")
    demo.revise("R-006", "transformador: más probable", probability=25, basis="El fabricante reprogramó las pruebas de fábrica.")
    demo.revise("R-003", "talud: cambia la probabilidad", probability=45, basis="El talud mostró nuevas grietas tras las lluvias.")

    log("2) Evaluaciones residuales (escenario mitigado) de los riesgos cuantificados")
    done = 0
    for row in demo.b("riskRegister.list")["rows"]:
        cells, rid = row["cells"], row["riskId"]
        if row["status"] != "identified" or cells.get("RiskType") != "Threat" or not cells.get("Current.ProbabilityPct"):
            continue
        if demo.current(rid, "Residual"):
            continue
        quant = analysis._quantification(demo.run, demo.scope, rid)
        if not quant or not (quant["costo"] or quant["plazo"]):
            continue
        prob = max(1, round(float(cells["Current.ProbabilityPct"]) * 0.45))
        current_levels = {p["perspectiveId"]: p["impactLevel"] for p in demo.current(rid).get("perspectives", [])}
        top = max(current_levels, key=lambda k: current_levels[k] or 0)
        current_levels[top] = max(1, (current_levels[top] or 1) - 1)          # las acciones también reducen el impacto máximo
        try:
            demo.evaluate(rid, "Residual", probability=prob, impacts=current_levels, basis="Probabilidad esperada con las acciones de respuesta aplicadas.")
            done += 1
        except automation.ApuriskError as error:
            log(f"  {rid}: no se pudo crear la residual ({error.message[:80]})")
    log(f"  residuales creadas: {done}")

    log("3) Acciones: vencidas, por vencer y con avance")
    actions = demo.b("riskActions.list")
    open_by_risk: dict[str, list[dict[str, Any]]] = {}
    for item in actions:
        if item["status"] in ("planned", "in_progress"):
            open_by_risk.setdefault(item["riskId"], []).append(item)
    plan = [
        ("R-001", 0, -8, "in_progress", "20"), ("R-004", 0, -4, "in_progress", "35"), ("R-031", 0, -2, "in_progress", "10"),
        ("R-003", 0, 3, "in_progress", "45"), ("R-002", 0, 2, "in_progress", "30"), ("R-021", 0, 6, "planned", ""), ("R-005", 0, 1, "in_progress", "50"),
    ]
    for risk_id, position, offset, status, progress in plan:
        candidates = open_by_risk.get(risk_id) or []
        if len(candidates) <= position:
            log(f"  {risk_id}: sin acción abierta, se omite")
            continue
        action = candidates[position]
        try:
            demo.set_action(action, today + timedelta(days=offset), status=status, progress=progress)
            log(f"  {action['actionId']} ({risk_id}) vence {today + timedelta(days=offset)} · {status} · avance {progress or '—'}")
        except automation.ApuriskError as error:
            log(f"  {action['actionId']} ({risk_id}): no se pudo cambiar ({error.message[:90]})")
    for risk_id in ("R-001", "R-003", "R-004", "R-002"):          # avance en otras acciones en curso, para que no todo falte
        for action in (open_by_risk.get(risk_id) or [])[1:3]:
            if action["status"] == "in_progress":
                try:
                    demo.set_action(action, date.fromisoformat(action["dueDate"]), progress="25")
                except automation.ApuriskError as error:
                    log(f"  {action['actionId']}: sin avance ({error.message[:70]})")

    log("4) Prioritarios con problemas (responsable, información, antigüedad)")
    # El add-in no deja que un riesgo publicado se quede sin responsable o sin causa: para el caso de demostración se vacían las celdas a mano.
    demo.write_text("RiskMasterTable", "RiskId", "R-027", {"RiskOwnerId": ""})
    log("  R-027 (Alto) sin responsable")
    demo.write_text("RiskMasterTable", "RiskId", "R-021", {"Cause": ""})
    log("  R-021 (Alto) sin causa: información incompleta")
    demo.age_risk("R-024", 46)
    demo.age_risk("R-026", 41)
    log("  R-024 y R-026 sin actualizar hace más de 30 días")

    app.ActiveWorkbook.Save()
    log("Libro guardado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
