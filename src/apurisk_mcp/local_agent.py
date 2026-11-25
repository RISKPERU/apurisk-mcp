"""Outbound-only Windows agent for the single-user remote MCP pilot."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from . import server


OPERATIONS = {
    "apurisk_status": server.apurisk_status,
    "apurisk_list_risks": server.apurisk_list_risks,
    "apurisk_get_risk": server.apurisk_get_risk,
    "apurisk_bowtie_get": server.apurisk_bowtie_get,
    "apurisk_select_risk": server.apurisk_select_risk,
    "apurisk_simulation_open": server.apurisk_simulation_open,
    "apurisk_simulation_view": server.apurisk_simulation_view,
    "apurisk_simulation_focus": server.apurisk_simulation_focus,
    "apurisk_simulation_configure": server.apurisk_simulation_configure,
    "apurisk_simulation_risk": server.apurisk_simulation_risk,
    "apurisk_simulation_correlation": server.apurisk_simulation_correlation,
    "apurisk_simulation_run": server.apurisk_simulation_run,
    "apurisk_simulation_results": server.apurisk_simulation_results,
    "apurisk_simulation_explore": server.apurisk_simulation_explore,
    "apurisk_simulation_export": server.apurisk_simulation_export,
}


def execute(job: dict[str, Any]) -> dict[str, Any]:
    request_id = job.get("id")
    operation = job.get("operation")
    try:
        result = OPERATIONS[operation](**job.get("arguments", {}))
        return {"id": request_id, "result": result}
    except Exception as exc:  # report Excel/Add-in errors to the waiting MCP call
        return {"id": request_id, "error": str(exc)}


def main() -> None:
    url = os.environ.get("APURISK_MCP_URL", "").rstrip("/")
    token = os.environ.get("APURISK_MCP_AGENT_TOKEN", "")
    if not url.startswith("https://") or len(token) < 32:
        raise SystemExit("Configure APURISK_MCP_URL (https) y APURISK_MCP_AGENT_TOKEN (32+ caracteres).")
    headers = {"Authorization": f"Bearer {token}"}
    print("Agente ApuRisk conectado al gateway; esperando solicitudes. Ctrl+C para salir.", flush=True)
    with httpx.Client(headers=headers, timeout=30.0) as client:
        while True:
            try:
                response = client.get(f"{url}/agent/next")
                response.raise_for_status()
                job = response.json().get("job")
                if job:
                    reply = client.post(f"{url}/agent/result", json=execute(job))
                    reply.raise_for_status()
            except KeyboardInterrupt:
                return
            except (httpx.HTTPError, ValueError) as exc:
                print(f"Conexión no disponible: {exc}. Reintentando en 5 s.", flush=True)
                time.sleep(5)


if __name__ == "__main__":
    main()
