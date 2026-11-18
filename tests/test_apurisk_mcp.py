import json

import pytest

from apurisk_mcp import automation, install_check, risks
from apurisk_mcp.automation import ApuriskError


class FakeAddIn:
    """Imita la puerta del add-in: guarda un Registro en memoria y responde como lo hace el puente real."""

    def __init__(self, tables_exist=True):
        self.tables_exist = tables_exist
        self.rows = []
        self.sent = []
        self.next = 1

    def _snapshot(self):
        return {"success": True, "payload": {"tablesExist": self.tables_exist, "rows": json.loads(json.dumps(self.rows))}}

    def _row(self, risk_id):
        return next(row for row in self.rows if row["riskId"] == risk_id)

    def __call__(self, text):
        request = json.loads(text)
        self.sent.append(request)
        op = request["op"]
        if op == "status":
            return json.dumps({"ok": True, "protocol": 1, "workbookScopeId": "scope-1", "workbookName": "Mina.xlsx"})
        if op == "ribbon.list":
            return json.dumps({"ok": True, "commands": ["BowTie", "RegistroRiesgos"]})
        if op == "ribbon.run":
            return json.dumps({"ok": True, "opened": request["name"]})
        assert op == "bridge.invoke"
        payload, kind = request["payload"], request["type"]
        if kind == "riskRegister.list":
            return json.dumps({"ok": True, "bridge": self._snapshot()})
        if kind == "riskRegister.createDraft":
            row = {"riskId": f"R-{self.next:03d}", "fingerprint": "f0", "status": "draft", "cells": {}, "validation": {"completeness": "incomplete", "missingRequired": ["RiskName"]}, "allowedTransitions": []}
            self.next += 1
            self.rows.append(row)
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": json.loads(json.dumps(row))}})
        if kind == "riskRegister.updateFields":
            row = self._row(payload["riskId"])
            if row["fingerprint"] != payload["fingerprint"]:
                return json.dumps({"ok": True, "bridge": {"success": False, "error": {"code": "conflict", "message": "La fila cambió.", "details": ["Recarga."]}}})
            row["cells"].update(payload["changes"])
            row["fingerprint"] += "x"
            row["validation"] = {"completeness": "complete", "missingRequired": []}
            row["allowedTransitions"] = ["identified"]
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": json.loads(json.dumps(row))}})
        if kind == "riskRegister.transition":
            row = self._row(payload["riskId"])
            row["status"] = payload["toStatus"]
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": json.loads(json.dumps(row))}})
        if kind == "riskRegister.preflight":
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": {"canCreateRegister": False, "checks": [{"state": "missing", "message": "Confirma el perfil de criterios."}]}}})
        raise AssertionError(kind)


def test_status_and_ribbon_round_trip():
    add_in = FakeAddIn()
    assert automation.status(add_in)["workbookScopeId"] == "scope-1"
    assert automation.ribbon_commands(add_in) == ["BowTie", "RegistroRiesgos"]
    assert automation.run_ribbon(add_in, "BowTie") == "BowTie"


def test_addin_rejection_becomes_an_error_with_its_code():
    def run(_):
        return json.dumps({"ok": False, "error": {"code": "unknown_command", "message": "No existe."}})

    with pytest.raises(ApuriskError) as caught:
        automation.run_ribbon(run, "Nada")
    assert caught.value.code == "unknown_command"


def test_spooled_responses_are_read_and_the_file_is_removed(tmp_path):
    path = tmp_path / "respuesta.json"
    path.write_text(json.dumps({"ok": True, "commands": ["A"]}), encoding="utf-8")
    result = automation.call(lambda _: json.dumps({"ok": True, "spooledTo": str(path)}), {"op": "ribbon.list"})
    assert result["commands"] == ["A"]
    assert not path.exists()


@pytest.mark.parametrize("answer", ["", "   ", "no es json"])
def test_unreadable_answers_are_errors(answer):
    with pytest.raises(ApuriskError):
        automation.call(lambda _: answer, {"op": "status"})


def test_create_risk_creates_a_draft_and_writes_the_fields():
    add_in = FakeAddIn()
    created = risks.create_risk(add_in, "scope-1", {"RiskName": "Falla de chancadora", "RiskType": "Threat", "Event": "Detención no planificada", "Cause": None})
    assert created["riskId"] == "R-001"
    assert created["status"] == "draft"
    assert created["RiskName"] == "Falla de chancadora"
    assert "Cause" not in created
    update = next(item for item in add_in.sent if item.get("type") == "riskRegister.updateFields")
    assert update["payload"]["changes"] == {"RiskName": "Falla de chancadora", "RiskType": "Threat", "Event": "Detención no planificada"}
    assert update["payload"]["fingerprint"] == "f0"


def test_create_risk_can_publish():
    add_in = FakeAddIn()
    created = risks.create_risk(add_in, "scope-1", {"RiskName": "Derrumbe de talud"}, publish=True)
    assert created["status"] == "identified"


def test_create_risk_does_not_touch_the_register_with_invalid_fields():
    add_in = FakeAddIn()
    with pytest.raises(ApuriskError):
        risks.create_risk(add_in, "scope-1", {"Current.MatrixLevel": "Alto"})
    with pytest.raises(ApuriskError):
        risks.create_risk(add_in, "scope-1", {"RiskType": "Peligro"})
    assert add_in.sent == []


def test_bridge_errors_keep_their_code_and_details():
    add_in = FakeAddIn()
    risks.create_risk(add_in, "scope-1", {"RiskName": "A"})
    with pytest.raises(ApuriskError) as conflict:
        automation.bridge(add_in, "riskRegister.updateFields", {"riskId": "R-001", "fingerprint": "viejo", "changes": {}})
    assert conflict.value.code == "conflict"
    assert conflict.value.details == ["Recarga."]


def test_listing_requires_the_register_and_filters_by_status():
    with pytest.raises(ApuriskError) as missing:
        risks.list_risks(FakeAddIn(tables_exist=False), "scope-1")
    assert missing.value.code == "register_missing"

    add_in = FakeAddIn()
    risks.create_risk(add_in, "scope-1", {"RiskName": "A"}, publish=True)
    risks.create_risk(add_in, "scope-1", {"RiskName": "B"})
    assert [item["RiskName"] for item in risks.list_risks(add_in, "scope-1", "draft")] == ["B"]
    assert len(risks.list_risks(add_in, "scope-1")) == 2


def test_create_register_reports_the_missing_prerequisites():
    with pytest.raises(ApuriskError) as caught:
        risks.create_register(FakeAddIn(tables_exist=False), "scope-1")
    assert caught.value.code == "prerequisites_missing"
    assert "Confirma el perfil de criterios." in caught.value.details


def test_unknown_status_is_rejected_before_calling_the_addin():
    add_in = FakeAddIn()
    with pytest.raises(ApuriskError):
        risks.transition(add_in, "scope-1", "R-001", "borrado")
    assert add_in.sent == []


@pytest.mark.parametrize("entry,channel", [
    ('/R "C:\\Users\\yo\\AppData\\Local\\ApuriskAddIn\\Apurisk.ExcelAddIn64.xll"', "current"),
    ('/R "D:\\x\\Apurisk.ExcelAddIn64-packed.xll"', "current"),
    ('/R "C:\\ApuriskOldAddIn\\Apurisk.Old.ExcelAddIn64.xll"', "old"),
])
def test_installed_addins_are_recognised(entry, channel):
    found = install_check.classify([entry])
    assert [item["channel"] for item in found] == [channel]
    assert found[0]["fileExists"] is False


def test_other_addins_are_ignored():
    assert install_check.classify(['/R "C:\\OtraHerramienta.xll"', "/R algo"]) == []
