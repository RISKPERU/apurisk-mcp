"""Pilot remote MCP gateway. Excel access remains in the Windows agent."""

from __future__ import annotations

import asyncio
import hmac
import os
import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


class Relay:
    """One Windows agent, in one gateway process, for the Friday pilot."""

    def __init__(self) -> None:
        self.jobs: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)
        self.pending: dict[str, asyncio.Future[Any]] = {}
        self.last_seen = 0.0

    async def invoke(self, operation: str, arguments: dict[str, Any]) -> Any:
        if time.monotonic() - self.last_seen > 45:
            raise RuntimeError("El agente local de ApuRisk está desconectado.")
        request_id = uuid.uuid4().hex
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            self.jobs.put_nowait({"id": request_id, "operation": operation, "arguments": arguments})
            return await asyncio.wait_for(future, timeout=50)
        except asyncio.QueueFull as exc:
            raise RuntimeError("El agente local tiene demasiadas solicitudes pendientes.") from exc
        except TimeoutError as exc:
            raise RuntimeError("El agente local no respondió a tiempo.") from exc
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()


def create_app(client_token: str, agent_token: str):
    if min(len(client_token), len(agent_token)) < 32 or hmac.compare_digest(client_token, agent_token):
        raise ValueError("Configure dos tokens distintos de al menos 32 caracteres.")

    relay = Relay()
    mcp = FastMCP("apurisk-remote", stateless_http=True, json_response=True)

    @mcp.tool()
    async def apurisk_status() -> dict[str, Any]:
        """Comprueba el Excel abierto y el estado del add-in ApuRisk en la PC conectada."""
        return await relay.invoke("apurisk_status", {})

    @mcp.tool()
    async def apurisk_list_risks(status: str | None = None, instance: int | None = None) -> list[dict[str, Any]]:
        """Lista los riesgos del libro activo. Usa instance si hay varios Excel abiertos."""
        return await relay.invoke("apurisk_list_risks", {"status": status, "instance": instance})

    @mcp.tool()
    async def apurisk_get_risk(risk_id: str, instance: int | None = None) -> dict[str, Any]:
        """Consulta un riesgo del libro activo por su ID, por ejemplo R-001."""
        return await relay.invoke("apurisk_get_risk", {"risk_id": risk_id, "instance": instance})

    @mcp.tool()
    async def apurisk_bowtie_get(risk_id: str, instance: int | None = None) -> dict[str, Any]:
        """Consulta el BowTie de un riesgo del libro activo."""
        return await relay.invoke("apurisk_bowtie_get", {"risk_id": risk_id, "instance": instance})

    @mcp.tool()
    async def apurisk_select_risk(risk_id: str, show: str | None = None, instance: int | None = None) -> str:
        """Selecciona el riesgo en Excel; show puede ser bowtie o evaluate."""
        if show not in (None, "bowtie", "evaluate"):
            raise ValueError("show debe ser bowtie, evaluate o vacío.")
        return await relay.invoke("apurisk_select_risk", {"risk_id": risk_id, "show": show, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_open(risk_id: str | None = None, run: bool = False, instance: int | None = None) -> dict[str, Any]:
        """Abre la Simulación actual en Excel; opcionalmente enfoca un riesgo y la ejecuta."""
        return await relay.invoke("apurisk_simulation_open", {"risk_id": risk_id, "run": run, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_view(step: str, reload: bool = False, instance: int | None = None) -> dict[str, Any]:
        """Muestra riesgos, correlaciones, simulacion o resultados; reload relee el libro."""
        return await relay.invoke("apurisk_simulation_view", {"step": step, "reload": reload, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_focus(risk_id: str | None = None, instance: int | None = None) -> dict[str, Any]:
        """Enfoca un riesgo; sin risk_id vuelve a todos los incluidos."""
        return await relay.invoke("apurisk_simulation_focus", {"risk_id": risk_id, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_configure(iterations: int | None = None, seed: int | None = None, method: str | None = None, instance: int | None = None) -> dict[str, Any]:
        """Ajusta iteraciones, semilla y muestreo lhs o montecarlo en la vista."""
        return await relay.invoke("apurisk_simulation_configure", {"iterations": iterations, "seed": seed, "method": method, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_risk(risk_id: str, include: bool | None = None, probability_pct: float | None = None, instance: int | None = None) -> dict[str, Any]:
        """Incluye un riesgo y ajusta su probabilidad de ocurrencia en la simulación."""
        return await relay.invoke("apurisk_simulation_risk", {"risk_id": risk_id, "include": include, "probability_pct": probability_pct, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_correlation(a: str, b: str, rho: float | None = None, remove: bool = False, instance: int | None = None) -> dict[str, Any]:
        """Ajusta o quita correlación entre cost:R-001 y time:R-001."""
        return await relay.invoke("apurisk_simulation_correlation", {"a": a, "b": b, "rho": rho, "remove": remove, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_run(iterations: int | None = None, seed: int | None = None, method: str | None = None, instance: int | None = None) -> dict[str, Any]:
        """Ejecuta la vista actual y devuelve medias, percentiles y sensibilidad por riesgo."""
        return await relay.invoke("apurisk_simulation_run", {"iterations": iterations, "seed": seed, "method": method, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_results(instance: int | None = None) -> dict[str, Any]:
        """Lee el resumen de la última simulación y el estado de su exportación."""
        return await relay.invoke("apurisk_simulation_results", {"instance": instance})

    @mcp.tool()
    async def apurisk_simulation_explore(cost: float | None = None, time: float | None = None, bins: str | None = None, show_cdf: bool | None = None, iteration: int | None = None, jump: str | None = None, instance: int | None = None) -> dict[str, Any]:
        """Cambia objetivos de costo/duración, histograma y caso explorado en Resultados."""
        return await relay.invoke("apurisk_simulation_explore", {"cost": cost, "time": time, "bins": bins, "show_cdf": show_cdf, "iteration": iteration, "jump": jump, "instance": instance})

    @mcp.tool()
    async def apurisk_simulation_export(instance: int | None = None) -> dict[str, Any]:
        """Pulsa Exportar a Excel en Resultados y confirma las hojas creadas."""
        return await relay.invoke("apurisk_simulation_export", {"instance": instance})

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "agentConnected": time.monotonic() - relay.last_seen <= 45})

    async def next_job(_request: Request) -> JSONResponse:
        relay.last_seen = time.monotonic()
        deadline = time.monotonic() + 20
        while True:
            try:
                job = await asyncio.wait_for(relay.jobs.get(), timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                return JSONResponse({"job": None})
            if job["id"] in relay.pending:
                relay.last_seen = time.monotonic()
                return JSONResponse({"job": job})
            if time.monotonic() >= deadline:
                return JSONResponse({"job": None})

    async def complete_job(request: Request) -> JSONResponse:
        body = await request.json()
        request_id = body.get("id")
        if not isinstance(request_id, str):
            return JSONResponse({"error": "missing_id"}, status_code=400)
        future = relay.pending.get(request_id)
        if future is None or future.done():
            return JSONResponse({"error": "expired_or_unknown_job"}, status_code=404)
        if "error" in body:
            future.set_exception(RuntimeError(str(body["error"])))
        elif "result" in body:
            future.set_result(body["result"])
        else:
            return JSONResponse({"error": "missing_result"}, status_code=400)
        return JSONResponse({"accepted": True})

    control = Starlette(routes=[
        Route("/health", health),
        Route("/agent/next", next_job, methods=["GET"]),
        Route("/agent/result", complete_job, methods=["POST"]),
    ])
    protocol = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            await protocol(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/health":
            await control(scope, receive, send)
            return
        expected = agent_token if path.startswith("/agent/") else client_token
        header = next((value for key, value in scope.get("headers", []) if key.lower() == b"authorization"), b"")
        if not hmac.compare_digest(header, ("Bearer " + expected).encode("utf-8")):
            await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
            return
        await (control if path.startswith("/agent/") else protocol)(scope, receive, send)

    return app


def from_environment():
    return create_app(os.environ.get("APURISK_MCP_CLIENT_TOKEN", ""), os.environ.get("APURISK_MCP_AGENT_TOKEN", ""))
