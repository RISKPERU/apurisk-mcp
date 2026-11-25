"""Named controls for the current ApuRisk Simulation WebView."""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import automation
from .automation import ApuriskError, Runner


WINDOW = "simulacion"


def new_id() -> str:
    return uuid.uuid4().hex


def state(run: Runner, scope: str) -> dict[str, Any]:
    return automation.bridge(run, "simulation.result.get", {"workbookScopeId": scope})


def command(run: Runner, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    delivered = automation.ui_command(run, WINDOW, name, payload)
    if delivered < 1:
        raise ApuriskError("simulation_window_closed", "Abre la vista de Simulación antes de usar esta herramienta.")
    return {"window": WINDOW, "command": name, "delivered": delivered}


def wait_for(run: Runner, scope: str, field: str, key: str, value: str, seconds: float = 35) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        snapshot = state(run, scope)
        current = snapshot.get(field)
        if isinstance(current, dict) and current.get(key) == value and current.get("status") in ("done", "error"):
            if current["status"] == "error":
                raise ApuriskError("simulation_failed", str(current.get("message") or "La operación de simulación falló."))
            return current
        time.sleep(0.3)
    return {"status": "pending", key: value, "message": "La vista todavía está procesando. Consulta el estado de la simulación de nuevo."}


def run_simulation(run: Runner, scope: str, iterations: int | None = None, seed: int | None = None, method: str | None = None, risk_id: str | None = None) -> dict[str, Any]:
    if iterations is not None and (not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations <= 100000):
        raise ApuriskError("invalid_iterations", "Las iteraciones deben estar entre 1 y 100 000.")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise ApuriskError("invalid_seed", "La semilla debe ser un número entero.")
    if method is not None and method not in ("lhs", "montecarlo"):
        raise ApuriskError("invalid_method", "El método debe ser lhs o montecarlo.")
    run_id = uuid.uuid4().hex
    command(run, "run", {"runId": run_id, "iterations": iterations, "seed": seed, "method": method, "riskId": risk_id})
    return wait_for(run, scope, "result", "runId", run_id)


def export_simulation(run: Runner, scope: str) -> dict[str, Any]:
    snapshot = state(run, scope)
    if not isinstance(snapshot.get("result"), dict) or snapshot["result"].get("status") != "done":
        raise ApuriskError("no_results", "Ejecuta la simulación antes de exportar.")
    export_id = uuid.uuid4().hex
    command(run, "export", {"exportId": export_id})
    return wait_for(run, scope, "export", "exportId", export_id)
