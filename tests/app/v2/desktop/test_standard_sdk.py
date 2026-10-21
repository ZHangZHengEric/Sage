
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.application import SAgentApplication
    from typing import Any

import json

import pytest

from app.v2.desktop.backend.schemas import DesktopRunRequest, ModelProviderPatch, RunMessage
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.model import ScriptedModelProvider


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_desktop_uses_standard_registered_execution_and_revision_recovery(tmp_path, monkeypatch):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(settings.model_copy(update={"component_selections": {
        **settings.component_selections,
        "agent.continuation-policy": "sage.agent.continuation.deterministic",
        "tool.selection-policy": "sage.tool-selection.direct",
        "memory.recall-query": "sage.memory.recall-query.direct",
    }}))
    await service.list_agents("user")
    await service.patch_model_provider("model_main", ModelProviderPatch(
        model="model-a", base_url="https://model.invalid/v1", api_keys=["secret"],
    ), "user")
    agent = await service._agent("sage", "user")
    await service.catalog.save_agent(agent.model_copy(update={"config": {
        **agent.config, "agentMode": "simple", "availableTools": [], "availableSkills": [],
    }}))
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
    from sagents.v2.model import ModelStreamEvent, ModelEventKind, ModelResponse
    model = ScriptedModelProvider((ScriptedModelStep(events=(ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(response_id="response", text="done", finish_reason="stop"),
    ),)),))
    async def model_provider(*args, **kwargs):
        return model
    monkeypatch.setattr(service, "_model_provider", model_provider)
    try:
        frames = [json.loads(frame) async for frame in service.run_events(DesktopRunRequest(
            agent_id="sage", messages=[RunMessage(role="user", text="hello")],
        ), "user")]
        assert any(frame.get("type") == "run.completed" for frame in frames), frames
        handle = frames[0]["handle"]
        context = service._context("user")
        loaded = await cast('SAgentApplication', service.application).agent_for_run(handle["run_id"], context)
        command = await service.session_store.get_start_command(handle["run_id"])
        assert command.agent_id == loaded.id
        assert command.resolved_spec_hash == loaded.composition_hash
        assert (cast('Any', await cast('SAgentApplication', service.application).execution_configuration(handle["run_id"], context))).provider_id
    finally:
        await service.close()
