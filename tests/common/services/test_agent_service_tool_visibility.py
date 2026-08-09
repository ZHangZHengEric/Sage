from __future__ import annotations

import pytest

from common.services import agent_service
from sagents.tool.impl.apply_patch_tool import ApplyPatchTool
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy


@pytest.mark.asyncio
async def test_auto_generate_agent_hides_explicit_only_tools_by_default(monkeypatch):
    manager = ToolManager(is_auto_discover=False, isolated=True)
    manager.tools = {
        "apply_patch": ApplyPatchTool.apply_patch._tool_spec,
    }
    captured = {}

    async def resolve_model_client(user_id):
        return object(), "test-model"

    class FakeAutoGenAgentFunc:
        async def generate_agent_config(self, **kwargs):
            captured.update(kwargs)
            return {"name": "generated"}

    monkeypatch.setattr(agent_service, "_resolve_model_client", resolve_model_client)
    monkeypatch.setattr(
        "sagents.tool.tool_manager.get_tool_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "sagents.utils.auto_gen_agent.AutoGenAgentFunc",
        FakeAutoGenAgentFunc,
    )

    result = await agent_service.auto_generate_agent("Generate an agent")

    proxy = captured["tool_manager"]
    assert isinstance(proxy, ToolProxy)
    assert proxy.get_tool("apply_patch") is None
    assert proxy.get_openai_tools() == []
    assert result["name"] == "generated"
