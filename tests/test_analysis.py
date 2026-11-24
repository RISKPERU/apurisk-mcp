import json

import pytest

from apurisk_mcp import analysis
from apurisk_mcp.automation import ApuriskError

TODAY = "2026-11-20"


def row(risk_id, name, level, owner="m1", updated="2026-11-13T03:00:00Z", evaluated="2026-11-10", missing=None, status="identified", evaluation_status="current"):
    return {
        "riskId": risk_id, "status": status,
        "cells": {"RiskName": name, "RiskType": "Threat", "RiskOwnerId": owner, "Current.MatrixLevel": level, "UpdatedAt": updated, "Current.EvaluationDate": evaluated,
                  "Current.EvaluationStatus": evaluation_status, "CompletenessStatus": "Incompleto" if missing else "Completo"},
        "validation": {"completeness": "incomplete" if missing else "complete", "missingRequired": missing or []},
    }


def revision(n, level_name, level_value, prob, impacts, date="2026-10-24"):
    return {"revision": n, "isConfirmed": True, "probabilityPct": prob, "consolidatedLevelName": level_name, "consolidatedValue": level_value, "evaluationDate": date,
            "perspectives": [{"perspectiveId": k, "impactLevel": v} for k, v in impacts.items()]}


class FakeAddIn:
    def __init__(self):
        self.rows = [
            row("R-001", "Molino SAG", "Extremo"),
            row("R-002", "Talud", "Alto", owner="", missing=["Cause"]),
            row("R-003", "Comunidad", "Alto", updated="2026-09-01T00:00:00Z", evaluated="2026-09-02"),
            row("R-004", "Bajo", "Bajo"),
            row("R-005", "Borrador", None, owner="", status="draft", evaluation_status="pending"),
        ]
        self.history = {
            "R-001": [revision(1, "Alto", 3, 55, {"financial": 3, "schedule": 3}), revision(2, "Extremo", 4, 65, {"financial": 3, "schedule": 4}, "2026-11-18")],
            "R-004": [revision(1, "Bajo", 1, 10, {"financial": 1}), revision(2, "Bajo", 1, 10, {"financial": 1}, "2026-11-18")],
            "R-003": [revision(1, "Alto", 3, 50, {"financial": 3})],
        }
        self.actions = [
            {"actionId": "A-1", "riskId": "R-001", "description": "Adelantar OC", "actionType": "preventive", "ownerId": "m5", "dueDate": "2026-11-15", "status": "in_progress", "progressPct": ""},
            {"actionId": "A-2", "riskId": "R-001", "description": "Inspección", "actionType": "mitigating", "ownerId": "m5", "dueDate": "2026-11-24", "status": "planned", "progressPct": "10"},
            {"actionId": "A-3", "riskId": "R-003", "description": "Mesa de diálogo", "actionType": "mitigating", "ownerId": "m1", "dueDate": "2026-12-30", "status": "planned", "progressPct": ""},
            {"actionId": "A-4", "riskId": "R-004", "description": "Hecha", "actionType": "mitigating", "ownerId": "m1", "dueDate": "2026-11-01", "status": "done", "progressPct": "100"},
        ]

    def __call__(self, text):
        request = json.loads(text)
        kind, payload = request["type"], request["payload"]
        data = {
            "riskRegister.list": {"tablesExist": True, "rows": self.rows},
            "controls.load": {"reviewers": [{"id": "m1", "name": "Ana Pérez"}, {"id": "m5", "name": "Rosa Quispe"}],
                              "risks": [{"id": "R-001", "barriers": [{"status": "Operational"}, {"status": "Partial"}, {"status": "Proposed"}]}]},
            "riskEvaluation.history": self.history.get(payload.get("riskId"), []) if payload.get("scenario") == "Current" else [],
            "riskActions.list": [a for a in self.actions if not payload.get("riskId") or a["riskId"] == payload["riskId"]],
            "bowTie.list": [{"id": "bt-1"}] if payload.get("riskId") == "R-001" else [],
            "bowTie.get": {"Quantification": {"IncludeCost": True, "IncludeSchedule": False, "Cost": {"Min": 1, "MostLikely": 2, "Max": 3}, "Schedule": {}}},
        }[kind]
        return json.dumps({"ok": True, "bridge": {"success": True, "payload": data}})


def test_risk_health_flags_priority_risks_first_and_explains_each_problem():
    data = analysis.risk_health(FakeAddIn(), "s", today=TODAY)
    ids = [r["riskId"] for r in data["riesgos"]]
    assert ids[:2] == ["R-003", "R-002"]
    stale = data["riesgos"][0]
    assert stale["diasSinActualizar"] == 79 and "sin actualizar hace 79 días" in stale["problemas"]
    r2 = data["riesgos"][1]
    assert "sin responsable" in r2["problemas"] and r2["camposFaltantes"] == ["Cause"] and r2["responsable"]["nombre"] is None
    assert data["prioritariosConProblemas"] == 2 and "R-001" not in ids and "R-004" not in ids


def test_risk_health_priority_only_drops_the_rest():
    ids = [r["riskId"] for r in analysis.risk_health(FakeAddIn(), "s", priority_only=True, today=TODAY)["riesgos"]]
    assert ids == ["R-003", "R-002"]


def test_risk_changes_compares_last_two_revisions_and_names_what_changed():
    data = analysis.risk_changes(FakeAddIn(), "s")
    assert [r["riskId"] for r in data["riesgos"]] == ["R-001"]
    change = data["riesgos"][0]
    assert change["nivel"] == {"antes": "Alto", "despues": "Extremo", "variacion": "subió"}
    assert change["probabilidad"] == {"antes": 55, "despues": 65, "cambio": True}
    assert change["impacto"]["perspectivas"] == [{"perspectiva": "schedule", "antes": 3, "despues": 4}]
    assert change["controles"]["porEstado"] == {"Operational": 1, "Partial": 1, "Proposed": 1}
    assert data["subieronDeNivel"] == 1 and data["sinRevisionAnterior"] == 1
    assert analysis.risk_changes(FakeAddIn(), "s", only_changed=False)["conCambios"] == 2


def test_risk_changes_rejects_unknown_scenario():
    with pytest.raises(ApuriskError):
        analysis.risk_changes(FakeAddIn(), "s", scenario="Optimista")


def test_actions_due_splits_overdue_and_upcoming_with_owner_names():
    data = analysis.actions_due(FakeAddIn(), "s", days=7, today=TODAY)
    assert [a["actionId"] for a in data["vencidas"]] == ["A-1"]
    assert data["vencidas"][0]["diasVencida"] == 5 and data["vencidas"][0]["responsable"] == {"id": "m5", "nombre": "Rosa Quispe"}
    assert [a["actionId"] for a in data["porVencer"]] == ["A-2"] and data["porVencer"][0]["diasParaVencer"] == 4
    assert data["vencidas"][0]["riesgo"] == "Molino SAG"


def test_risk_dossier_lists_what_is_missing():
    data = analysis.risk_dossier(FakeAddIn(), "s", "R-001", today=TODAY)
    assert data["cambioDesdeUltimaRevision"]["nivel"]["variacion"] == "subió"
    assert data["cuantificacion"]["costo"] is not None and data["cuantificacion"]["plazo"] is None
    gaps = " ".join(data["informacionFaltante"])
    for expected in ("Residual", "Solo está cuantificado el costo", "solo propuestos", "implementados solo en parte", "acción(es) vencida(s)"):
        assert expected in gaps
    assert data["accionesAbiertas"][0]["vencida"] is True


def test_risk_dossier_unknown_risk():
    with pytest.raises(ApuriskError) as error:
        analysis.risk_dossier(FakeAddIn(), "s", "R-999", today=TODAY)
    assert error.value.code == "risk_not_found"
