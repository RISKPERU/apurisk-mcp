"""ASGI entry point: uvicorn apurisk_mcp.remote_app:app."""

from .remote import from_environment

app = from_environment()
