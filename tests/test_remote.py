"""Real Streamable HTTP exchange through the gateway and a fake Windows agent."""

import asyncio
import socket

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from apurisk_mcp.local_agent import execute
from apurisk_mcp.remote import create_app
from apurisk_mcp import server, simulation


def test_simulation_open_uses_addin_bridge(monkeypatch):
    calls = []
    runner = lambda text: text
    monkeypatch.setattr(server, "_context", lambda instance: ("excel", runner, "book-1"))
    monkeypatch.setattr(server.risks, "get_risk", lambda run, scope, risk_id: calls.append(("risk", scope, risk_id)))
    monkeypatch.setattr(server.automation, "open_windows", lambda run: [])
    monkeypatch.setattr(server.automation, "bridge", lambda run, command, payload: calls.append(("bridge", command, payload)) or {"opened": True})
    result = server.apurisk_simulation_open("R-001", True)
    assert result["runRequested"] is True
    assert calls == [("risk", "book-1", "R-001"), ("bridge", "simulation.open", {"riskId": "R-001", "run": True})]


def test_agent_rejects_unknown_operation():
    reply = execute({"id": "1", "operation": "apurisk_bridge", "arguments": {}})
    assert reply["id"] == "1"
    assert "error" in reply


def test_simulation_run_and_export_return_published_result(monkeypatch):
    commands = []
    snapshot = {"result": None, "export": None}

    def send(_runner, _window, name, payload):
        commands.append((name, payload))
        if name == "run":
            snapshot["result"] = {"status": "done", "runId": payload["runId"], "cost": {"mean": 123}}
        if name == "export":
            snapshot["export"] = {"status": "done", "exportId": payload["exportId"], "sheets": ["Sim Resumen"]}
        return 1

    monkeypatch.setattr(simulation.automation, "ui_command", send)
    monkeypatch.setattr(simulation.automation, "bridge", lambda runner, name, payload: dict(snapshot))
    result = simulation.run_simulation(lambda x: x, "book-1", iterations=200, risk_id="R-001")
    assert result["cost"]["mean"] == 123
    assert commands[0][1]["riskId"] == "R-001"
    assert simulation.export_simulation(lambda x: x, "book-1")["sheets"] == ["Sim Resumen"]


def test_simulation_explore_returns_target_probability(monkeypatch):
    runner = lambda x: x
    monkeypatch.setattr(server, "_context", lambda instance: ("excel", runner, "book-1"))
    monkeypatch.setattr(simulation, "command", lambda run, name, payload=None: {"delivered": 1})
    monkeypatch.setattr(simulation, "wait_for", lambda run, scope, field, key, value: {"analysis": {"costProbability": 0.73}})
    assert server.apurisk_simulation_explore(cost=900000)["analysis"]["costProbability"] == 0.73


def test_remote_mcp_round_trip():
    async def scenario():
        client_key, agent_key = "c" * 40, "a" * 40
        app = create_app(client_key, agent_key)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            assert server.started
            url = f"http://127.0.0.1:{port}"
            async with httpx.AsyncClient() as http:
                assert (await http.get(f"{url}/mcp")).status_code == 401
                assert (await http.get(f"{url}/agent/next")).status_code == 401

            async def fake_agent():
                async with httpx.AsyncClient(headers={"Authorization": f"Bearer {agent_key}"}, timeout=25) as http:
                    for operation, value in (("apurisk_status", {"excelInstances": [{"workbooks": [{"name": "Piloto.xlsx"}]}]}),
                                             ("apurisk_simulation_results", {"result": {"status": "done", "cost": {"mean": 123}}})):
                        response = await http.get(f"{url}/agent/next")
                        response.raise_for_status()
                        job = response.json()["job"]
                        assert job["operation"] == operation
                        response = await http.post(f"{url}/agent/result", json={"id": job["id"], "result": value})
                        response.raise_for_status()

            agent = asyncio.create_task(fake_agent())
            async with httpx.AsyncClient(headers={"Authorization": f"Bearer {client_key}"}) as mcp_http:
                async with streamable_http_client(f"{url}/mcp", http_client=mcp_http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        assert "apurisk_status" in names
                        assert "apurisk_simulation_open" in names
                        assert {"apurisk_simulation_view", "apurisk_simulation_focus", "apurisk_simulation_configure", "apurisk_simulation_risk",
                                "apurisk_simulation_correlation", "apurisk_simulation_run", "apurisk_simulation_results",
                                "apurisk_simulation_explore", "apurisk_simulation_export"} <= names
                        assert "apurisk_bridge" not in names
                        result = await session.call_tool("apurisk_status", {})
                        assert "Piloto.xlsx" in str(result)
                        result = await session.call_tool("apurisk_simulation_results", {})
                        assert "123" in str(result)
            await agent
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())
