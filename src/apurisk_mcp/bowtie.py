"""Edición de diagramas BowTie: se lee el diagrama del add-in, se aplican los cambios pedidos y se guarda con el comando normal de ApuRisk.

Los nombres de propiedad son los del diagrama del add-in (PascalCase). Las probabilidades de ruta son fracciones 0..1 en el diagrama; aquí se piden
en porcentaje (0-100), como se ven en pantalla.
"""

from __future__ import annotations

import uuid
from typing import Any

from . import automation
from .automation import ApuriskError, Runner

SIDES = {"threat": "Threats", "consequence": "Consequences"}


def _new_id() -> str:
    return uuid.uuid4().hex


def _fraction(percent: Any) -> float | None:
    if percent is None:
        return None
    try:
        value = float(percent)
    except (TypeError, ValueError) as exc:
        raise ApuriskError("invalid_field", f"La probabilidad «{percent}» no es un número.") from exc
    if not 0 <= value <= 100:
        raise ApuriskError("invalid_field", "La probabilidad va de 0 a 100 (%).")
    return round(value / 100, 6)


def _text(value: Any, field: str) -> str:
    name = str(value).strip() if value is not None else ""
    if not name:
        raise ApuriskError("invalid_field", f"Falta «{field}».")
    return name


def new_barrier(spec: dict[str, Any]) -> dict[str, Any]:
    barrier: dict[str, Any] = {"Id": _new_id(), "Name": _text(spec.get("name"), "name de la barrera"), "Status": "Proposed",
                               "OwnerIds": [], "DocumentIds": [], "MitigationEffect": "ConsequenceProbability"}
    if spec.get("description"):
        barrier["Description"] = str(spec["description"])
    if spec.get("owner_id"):
        barrier["OwnerId"] = str(spec["owner_id"])
        barrier["OwnerIds"] = [str(spec["owner_id"])]
    return barrier


def new_branch(spec: dict[str, Any]) -> dict[str, Any]:
    branch: dict[str, Any] = {"Id": _new_id(), "Name": _text(spec.get("name"), "name"), "Description": str(spec.get("description") or ""), "Barriers": []}
    probability = _fraction(spec.get("probability_pct"))
    if probability is not None:
        branch["Probability"] = probability
    branch["Barriers"] = [new_barrier(item) for item in spec.get("barriers") or []]
    return branch


def find_branch(diagram: dict[str, Any], side: str, reference: str) -> dict[str, Any]:
    if side not in SIDES:
        raise ApuriskError("invalid_field", "«side» debe ser threat (causa/amenaza) o consequence.")
    wanted = _text(reference, "branch").lower()
    branches = diagram.get(SIDES[side]) or []
    for branch in branches:
        if str(branch.get("Id", "")).lower() == wanted:
            return branch
    matches = [branch for branch in branches if str(branch.get("Name", "")).strip().lower() == wanted]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ApuriskError("not_found", f"No hay {'una causa' if side == 'threat' else 'una consecuencia'} «{reference}» en el BowTie.")
    raise ApuriskError("ambiguous", f"Hay varias con el nombre «{reference}»; indica su Id.")


def apply_edits(
    diagram: dict[str, Any],
    hazard_name: str | None = None,
    hazard_description: str | None = None,
    top_event: str | None = None,
    threats: list[dict[str, Any]] | None = None,
    consequences: list[dict[str, Any]] | None = None,
    barriers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aplica los cambios al diagrama (lo modifica) y devuelve un resumen de lo hecho. Valida todo antes de tocar nada."""
    additions = {
        "Threats": [new_branch(item) for item in threats or []],
        "Consequences": [new_branch(item) for item in consequences or []],
    }
    # Las barreras pueden colgar de una rama del diagrama o de una que se agrega en esta misma llamada.
    scratch = {"Threats": list(diagram.get("Threats") or []) + additions["Threats"], "Consequences": list(diagram.get("Consequences") or []) + additions["Consequences"]}
    barrier_targets = []
    for item in barriers or []:
        side = str(item.get("side") or "")
        branch = find_branch(scratch, side, item.get("branch"))
        barrier_targets.append((branch, new_barrier(item)))

    if hazard_name is not None:
        diagram["HazardName"] = str(hazard_name)
    if hazard_description is not None:
        diagram["HazardDescription"] = str(hazard_description)
    if top_event is not None:
        diagram["TopEvent"] = str(top_event)
    for key, branches in additions.items():
        diagram.setdefault(key, [])
        diagram[key] = list(diagram[key]) + branches
    for branch, barrier in barrier_targets:
        branch.setdefault("Barriers", [])
        branch["Barriers"] = list(branch["Barriers"]) + [barrier]
    return {
        "threatsAdded": len(additions["Threats"]), "consequencesAdded": len(additions["Consequences"]),
        "barriersAdded": len(barrier_targets) + sum(len(branch["Barriers"]) for key in additions for branch in additions[key]),
    }


def summarize(diagram: dict[str, Any]) -> dict[str, Any]:
    def branch_view(branch: dict[str, Any]) -> dict[str, Any]:
        probability = branch.get("Probability")
        return {
            "id": branch.get("Id"), "name": branch.get("Name"), "description": branch.get("Description") or None,
            "probabilityPct": None if probability is None else round(float(probability) * 100, 4),
            "barriers": [{"id": item.get("Id"), "name": item.get("Name"), "status": item.get("Status"), "description": item.get("Description") or None} for item in branch.get("Barriers") or []],
        }

    return {
        "id": diagram.get("Id"), "riskId": diagram.get("LinkedRiskId"), "status": diagram.get("Status"),
        "hazardName": diagram.get("HazardName"), "topEvent": diagram.get("TopEvent"),
        "threats": [branch_view(branch) for branch in diagram.get("Threats") or []],
        "consequences": [branch_view(branch) for branch in diagram.get("Consequences") or []],
    }


def load(run: Runner, scope: str, risk_id: str) -> dict[str, Any] | None:
    """El primer BowTie vinculado al riesgo, o ``None`` si todavía no tiene."""
    items = automation.bridge(run, "bowTie.list", {"workbookScopeId": scope, "riskId": risk_id}) or []
    if not items:
        return None
    return automation.bridge(run, "bowTie.get", {"workbookScopeId": scope, "bowTieId": items[0]["id"]})


def edit(run: Runner, scope: str, risk_id: str, **changes: Any) -> dict[str, Any]:
    """Crea el BowTie del riesgo si no existe, aplica los cambios y lo guarda. El add-in avisa a las ventanas abiertas para que se actualicen."""
    diagram = load(run, scope, risk_id)
    created = diagram is None
    if created:
        diagram = automation.bridge(run, "bowTie.create", {"workbookScopeId": scope, "riskId": risk_id})
    done = apply_edits(diagram, **changes)
    saved = automation.bridge(run, "bowTie.save", diagram)
    return {"created": created, **done, "bowTie": summarize(saved)}
