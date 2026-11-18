"""Protocolo con la puerta de entrada del add-in (función oculta ``APURISK_AUTOMATION``).

Este módulo no conoce COM: recibe una función ``run(json_text) -> str`` (en producción, ``Application.Run`` de Excel), así que se
puede probar sin Excel.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

PROTOCOL_VERSION = 1
FUNCTION_NAME = "APURISK_AUTOMATION"

Runner = Callable[[str], str]


class ApuriskError(Exception):
    """Fallo esperado: lleva un código estable y, si existen, los detalles que el add-in da a la persona usuaria."""

    def __init__(self, code: str, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []

    def __str__(self) -> str:
        detail = (" " + " ".join(self.details)) if self.details else ""
        return f"[{self.code}] {self.message}{detail}"


def _decode(text: str) -> dict[str, Any]:
    """Interpreta la respuesta de Excel. Si el add-in la dejó en un archivo (más de 30 000 caracteres), la lee y la borra."""
    if not isinstance(text, str) or not text.strip():
        raise ApuriskError("empty_response", "El add-in no devolvió respuesta.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApuriskError("invalid_response", f"Respuesta del add-in ilegible: {exc}") from exc
    spooled = data.get("spooledTo")
    if spooled:
        try:
            with open(spooled, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        finally:
            try:
                os.remove(spooled)
            except OSError:
                pass
    return data


def call(run: Runner, request: dict[str, Any]) -> dict[str, Any]:
    """Envía una operación al add-in y devuelve su respuesta; lanza ``ApuriskError`` si el add-in la rechaza."""
    data = _decode(run(json.dumps(request, ensure_ascii=False)))
    if not data.get("ok", False):
        error = data.get("error") or {}
        raise ApuriskError(error.get("code", "failed"), error.get("message", "El add-in rechazó la operación."))
    return data


def bridge(run: Runner, type_: str, payload: dict[str, Any] | None = None) -> Any:
    """Ejecuta un comando del puente de la interfaz de ApuRisk y devuelve su ``payload``; lanza ``ApuriskError`` con el código del add-in."""
    reply = call(run, {"op": "bridge.invoke", "type": type_, "payload": payload or {}})["bridge"]
    if not reply.get("success", False):
        error = reply.get("error") or {}
        raise ApuriskError(error.get("code", "operation_failed"), error.get("message", "El comando falló."), error.get("details"))
    return reply.get("payload")


def status(run: Runner) -> dict[str, Any]:
    return call(run, {"op": "status"})


def ribbon_commands(run: Runner) -> list[str]:
    return list(call(run, {"op": "ribbon.list"})["commands"])


def run_ribbon(run: Runner, name: str) -> str:
    return call(run, {"op": "ribbon.run", "name": name})["opened"]
