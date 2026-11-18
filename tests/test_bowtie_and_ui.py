import json

import pytest

from apurisk_mcp import automation, bowtie
from apurisk_mcp.automation import ApuriskError


def base_diagram():
    return {
        "Id": "bt-1", "LinkedRiskId": "R-001", "HazardName": "Talud", "HazardDescription": "", "TopEvent": "Derrumbe", "Status": "Draft",
        "Threats": [{"Id": "t1", "Name": "Lluvia intensa", "Description": "", "Barriers": []}],
        "Consequences": [{"Id": "c1", "Name": "Paralización", "Description": "", "Barriers": []}],
        "Settings": {}, "WorkbookScopeId": "scope-1",
    }


class FakeBowTieAddIn:
    def __init__(self, diagram=None):
        self.diagram = diagram
        self.sent = []

    def __call__(self, text):
        request = json.loads(text)
        self.sent.append(request)
        op = request["op"]
        if op == "ui.windows":
            return json.dumps({"ok": True, "windows": ["registro"]})
        if op == "ui.refresh":
            return json.dumps({"ok": True, "windows": ["registro", "matriz"]})
        if op == "ui.command":
            return json.dumps({"ok": True, "delivered": 1})
        kind, payload = request["type"], request["payload"]
        if kind == "bowTie.list":
            items = [{"id": self.diagram["Id"]}] if self.diagram else []
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": items}})
        if kind == "bowTie.get":
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": self.diagram}})
        if kind == "bowTie.create":
            self.diagram = {**base_diagram(), "Threats": [], "Consequences": [], "HazardName": "", "TopEvent": ""}
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": self.diagram}})
        if kind == "bowTie.save":
            self.diagram = payload
            return json.dumps({"ok": True, "bridge": {"success": True, "payload": payload}})
        raise AssertionError(kind)


def test_edit_adds_threats_consequences_and_barriers_and_saves_once():
    add_in = FakeBowTieAddIn(base_diagram())
    result = bowtie.edit(
        add_in, "scope-1", "R-001", top_event="Colapso del talud",
        threats=[{"name": "Sismo", "probability_pct": 12.5, "barriers": [{"name": "Monitoreo sísmico", "description": "Sensores"}]}],
        consequences=[{"name": "Daño a equipos"}],
        barriers=[{"side": "threat", "branch": "lluvia intensa", "name": "Drenaje perimetral", "owner_id": "m1"}],
    )
    assert result["created"] is False
    assert (result["threatsAdded"], result["consequencesAdded"], result["barriersAdded"]) == (1, 1, 2)
    saved = add_in.diagram
    assert saved["TopEvent"] == "Colapso del talud"
    assert [branch["Name"] for branch in saved["Threats"]] == ["Lluvia intensa", "Sismo"]
    sismo = saved["Threats"][1]
    assert sismo["Probability"] == 0.125
    assert sismo["Barriers"][0]["Name"] == "Monitoreo sísmico" and sismo["Barriers"][0]["Status"] == "Proposed"
    assert saved["Threats"][0]["Barriers"][0]["OwnerIds"] == ["m1"]
    assert all(len(branch["Id"]) == 32 for branch in saved["Threats"][1:] + saved["Consequences"][1:])
    assert [item["type"] for item in add_in.sent if item.get("type", "").startswith("bowTie.save")] == ["bowTie.save"]


def test_edit_creates_the_bowtie_when_the_risk_has_none():
    add_in = FakeBowTieAddIn(None)
    result = bowtie.edit(add_in, "scope-1", "R-009", hazard_name="Planta", threats=[{"name": "Corte de energía"}])
    assert result["created"] is True
    assert add_in.diagram["HazardName"] == "Planta"
    assert result["bowTie"]["threats"][0]["name"] == "Corte de energía"


def test_an_invalid_edit_saves_nothing_and_changes_nothing():
    add_in = FakeBowTieAddIn(base_diagram())
    before = json.dumps(add_in.diagram, sort_keys=True)
    for bad in (
        {"threats": [{"name": "  "}]},
        {"threats": [{"name": "X", "probability_pct": 120}]},
        {"consequences": [{"name": "Y", "probability_pct": "mucho"}]},
        {"barriers": [{"side": "threat", "branch": "No existe", "name": "B"}]},
        {"barriers": [{"side": "lado", "branch": "t1", "name": "B"}]},
        {"barriers": [{"side": "threat", "branch": "t1", "name": ""}]},
    ):
        with pytest.raises(ApuriskError):
            bowtie.edit(add_in, "scope-1", "R-001", **bad)
    assert json.dumps(add_in.diagram, sort_keys=True) == before
    assert not any(item.get("type") == "bowTie.save" for item in add_in.sent)


def test_summary_shows_probability_as_percentage():
    diagram = base_diagram()
    diagram["Threats"][0]["Probability"] = 0.3
    view = bowtie.summarize(diagram)
    assert view["threats"][0]["probabilityPct"] == 30
    assert view["topEvent"] == "Derrumbe"


def test_ambiguous_branch_names_ask_for_the_id():
    diagram = base_diagram()
    diagram["Threats"].append({"Id": "t2", "Name": "lluvia intensa", "Description": "", "Barriers": []})
    with pytest.raises(ApuriskError) as caught:
        bowtie.find_branch(diagram, "threat", "Lluvia intensa")
    assert caught.value.code == "ambiguous"
    assert bowtie.find_branch(diagram, "threat", "t2")["Id"] == "t2"


def test_ui_helpers_talk_to_the_addin():
    add_in = FakeBowTieAddIn()
    assert automation.open_windows(add_in) == ["registro"]
    assert automation.refresh_windows(add_in) == ["registro", "matriz"]
    assert automation.ui_command(add_in, "matriz", "setFilter", {"key": "draft", "on": False}) == 1
    assert add_in.sent[-1] == {"op": "ui.command", "window": "matriz", "command": "setFilter", "payload": {"key": "draft", "on": False}}


def test_a_window_that_is_not_open_is_reported_by_the_addin():
    def run(_):
        return json.dumps({"ok": False, "error": {"code": "window_not_open", "message": "No hay una ventana abierta."}})

    with pytest.raises(ApuriskError) as caught:
        automation.ui_command(run, "matriz", "clearFilters")
    assert caught.value.code == "window_not_open"
