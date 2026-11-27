"""Outbound-only Windows agent for the single-user remote MCP pilot."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .remote import local_tools


# Todas las herramientas del MCP local: las mismas que publica el gateway remoto.
OPERATIONS = local_tools()

log = logging.getLogger("apurisk_mcp.agent")


def execute(job: dict[str, Any]) -> dict[str, Any]:
    request_id = job.get("id")
    operation = job.get("operation")
    try:
        result = OPERATIONS[operation](**job.get("arguments", {}))
        return {"id": request_id, "result": result}
    except Exception as exc:  # report Excel/Add-in errors to the waiting MCP call
        log.warning("%s falló: %s", operation, exc)
        return {"id": request_id, "error": str(exc)}


def log_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ApuriskMcp" / "agente.log"


def _configure_logging() -> None:
    # Con pythonw.exe (agente oculto) no hay consola: se escribe en un log que rota a 1 MB.
    if sys.stdout is not None:
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
    else:
        log_file().parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _single_instance() -> object | None:
    """Mutex de la sesión de Windows: dos agentes se repartirían las solicitudes. None si ya hay otro."""
    if sys.platform != "win32":
        return object()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ApuriskMcpAgent")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def main() -> None:
    _configure_logging()
    url = os.environ.get("APURISK_MCP_URL", "").rstrip("/")
    token = os.environ.get("APURISK_MCP_AGENT_TOKEN", "")
    if not url.startswith("https://") or len(token) < 32:
        log.error("Configure APURISK_MCP_URL (https) y APURISK_MCP_AGENT_TOKEN (32+ caracteres).")
        raise SystemExit(1)
    mutex = _single_instance()
    if mutex is None:
        log.info("El agente ApuRisk ya está en marcha en esta sesión; no se inicia otro.")
        return
    headers = {"Authorization": f"Bearer {token}"}
    log.info("Agente ApuRisk iniciado; atendiendo solicitudes de %s. Ctrl+C para salir.", url)
    failing = False
    with httpx.Client(headers=headers, timeout=30.0) as client:
        while True:
            try:
                response = client.get(f"{url}/agent/next")
                response.raise_for_status()
                if failing:
                    log.info("Conexión recuperada.")
                    failing = False
                job = response.json().get("job")
                if job:
                    reply = client.post(f"{url}/agent/result", json=execute(job))
                    reply.raise_for_status()
            except KeyboardInterrupt:
                return
            except (httpx.HTTPError, ValueError) as exc:
                # Solo el primer fallo de una racha: un corte largo no llena el log.
                if not failing:
                    log.warning("Conexión no disponible: %s. Reintentando cada 5 s.", exc)
                failing = True
                time.sleep(5)


if __name__ == "__main__":
    main()
