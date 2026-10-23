"""Desktop stdio settings survive persistence and reach the MCP transport."""
from contextlib import asynccontextmanager

import pytest

from app.v2.desktop.backend.catalog import DesktopMcpRecord, JsonDesktopCatalogStore
from app.v2.desktop.backend.schemas import MCPConnectionRequest
from tests.app.v2.desktop.sdk_fixture import desktop


@pytest.mark.asyncio
async def test_stdio_configuration_is_persisted_and_used_for_discovery(tmp_path, monkeypatch):
    observed = []

    @asynccontextmanager
    async def session(config):
        observed.append(config)

        class Session:
            async def list_tools(self):
                return {"tools": [{"name": "lookup", "description": "Lookup", "inputSchema": {
                    "type": "object", "properties": {},
                }}]}

        yield Session()

    monkeypatch.setattr("sagents.v2.tool.plugins.mcp._sdk_session", session)
    service, _, _ = desktop(tmp_path / "sage")
    request = MCPConnectionRequest(
        name="TauRetail", protocol="stdio", command="/project/.venv/bin/python",
        api_key="private-key", timeout_seconds=47,
        args=["-m", "evaluation_datasets.tau_bench.mcp_server", "--state", "/path with spaces/state.sqlite3"],
        env={"PYTHONPATH": "/project", "SAGE_RSI_CASE_PROTOCOL": "sage.rsi.case/v1"},
    )
    try:
        result = await service.add_mcp_connection(request, "alice")
        assert result["args"] == request.args
        assert result["env"] == request.env
        assert result["tool_count"] == 1
        assert result["connection_error"] == ""
        records = await JsonDesktopCatalogStore(service.catalog.path).list_mcp("alice")
        saved = next(record for record in records if record.name == "TauRetail")
        assert saved.args == tuple(request.args)
        assert saved.env == request.env
        config = next(config for config in observed if config.name == "TauRetail")
        assert config.command == request.command
        assert config.args == tuple(request.args)
        assert dict(config.env) == request.env

        await service.set_mcp_connection_enabled("TauRetail", False, "alice")
        update = MCPConnectionRequest.model_validate({
            **request.model_dump(exclude={"api_key", "timeout_seconds"}),
            "command": "/new/python", "args": ["-m", "updated_server"],
        })
        result = await service.update_mcp_connection("TauRetail", update, "alice")
        assert result["disabled"] is True
        assert result["command"] == "/new/python"
        assert "api_key" not in result
        records = await JsonDesktopCatalogStore(service.catalog.path).list_mcp("alice")
        saved = next(record for record in records if record.name == "TauRetail")
        assert saved.api_key == "private-key"
        assert saved.timeout_seconds == 47
        assert saved.env == request.env
        assert saved.args == ("-m", "updated_server")
        await service.set_mcp_connection_enabled("TauRetail", True, "alice")
        assert any(config.command == "/new/python" and config.args == saved.args for config in observed)
        with pytest.raises(ValueError, match="name cannot be changed"):
            await service.update_mcp_connection("TauRetail", update.model_copy(update={"name": "Other"}), "alice")
        with pytest.raises(ValueError, match="not found"):
            await service.update_mcp_connection("TauRetail", update, "bob")
        await service.catalog.save_mcp(DesktopMcpRecord(
            user_id="alice", name="AnyTool", protocol="streamable_http", kind="anytool"))
        with pytest.raises(ValueError, match="Built-in"):
            await service.update_mcp_connection("AnyTool", MCPConnectionRequest(
                name="AnyTool", protocol="stdio", command="python"), "alice")
    finally:
        await service.close()
