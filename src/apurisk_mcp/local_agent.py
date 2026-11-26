"""Outbound-only Windows agent for the single-user remote MCP pilot."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from .remote import local_tools


# Todas las herramientas del MCP local: las mismas que publica el gateway remoto.
OPERATIONS = local_tools()


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
