"""Pilot remote MCP gateway. Excel access remains in the Windows agent; the tools mirror the local MCP."""

from __future__ import annotations

import asyncio
import hmac
import inspect
import os
import time
import typing
import uuid
from typing import Any, Callable
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
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


def local_tools() -> dict[str, Callable[..., Any]]:
    """Herramientas `apurisk_*` del MCP local; el agente las ejecuta y el gateway publica las mismas."""
    from . import server

    return {name: function for name, function in inspect.getmembers(server, inspect.isfunction)
            if name.startswith("apurisk_") and function.__module__ == server.__name__}


def _relayed(relay: Relay, function: Callable[..., Any]) -> Callable[..., Any]:
    """Copia la firma y la descripción de la herramienta local; al llamarla, la reenvía al agente de Windows."""
    hints = typing.get_type_hints(function)
    signature = inspect.signature(function)
    parameters = [parameter.replace(annotation=hints.get(parameter.name, parameter.annotation)) for parameter in signature.parameters.values()]

    async def call(**arguments: Any) -> Any:
        return await relay.invoke(function.__name__, arguments)

    call.__name__ = function.__name__
    call.__doc__ = function.__doc__
    call.__signature__ = signature.replace(parameters=parameters, return_annotation=hints.get("return", signature.return_annotation))
    call.__annotations__ = hints
    return call


def create_app(client_token: str, agent_token: str, public_host: str | None = None):
    if min(len(client_token), len(agent_token)) < 32 or hmac.compare_digest(client_token, agent_token):
        raise ValueError("Configure dos tokens distintos de al menos 32 caracteres.")

    relay = Relay()
    # FastMCP solo acepta Host localhost por omisión (protección contra DNS rebinding): detrás del proxy de Hestia
    # llega el dominio público, que hay que permitir de forma explícita o Claude recibe 421.
    security = None
    if public_host:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[public_host, f"{public_host}:*"],
            allowed_origins=[f"https://{public_host}", "https://claude.ai"],
        )
    mcp = FastMCP("apurisk-remote", stateless_http=True, json_response=True, transport_security=security)

    # Las mismas herramientas que el MCP local (nombre, parámetros y descripción): el VPS solo las reenvía al agente.
    for function in local_tools().values():
        mcp.add_tool(_relayed(relay, function))

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
        authorized = hmac.compare_digest(header, ("Bearer " + expected).encode("utf-8"))
        # Los conectores personalizados de Claude no permiten cabeceras: la clave del cliente puede ir en la URL
        # (`/mcp?key=...`). Solo para /mcp; el agente sigue usando la cabecera.
        if not authorized and not path.startswith("/agent/"):
            keys = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("key", [])
            authorized = len(keys) == 1 and hmac.compare_digest(keys[0].encode("utf-8"), client_token.encode("utf-8"))
        if not authorized:
            await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
            return
        await (control if path.startswith("/agent/") else protocol)(scope, receive, send)

    return app


def from_environment():
    public_host = os.environ.get("APURISK_MCP_PUBLIC_HOST", "").strip().lower()
    if not public_host or "/" in public_host:
        raise ValueError("Configure APURISK_MCP_PUBLIC_HOST con el dominio público, por ejemplo mcp.tudominio.com (sin https://).")
    return create_app(os.environ.get("APURISK_MCP_CLIENT_TOKEN", ""), os.environ.get("APURISK_MCP_AGENT_TOKEN", ""), public_host)
