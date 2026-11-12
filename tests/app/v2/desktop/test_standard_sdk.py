
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.application import SAgentApplication
    from typing import Any

import json
from types import SimpleNamespace

import pytest

from app.v2.desktop.backend.schemas import DesktopRunRequest, ModelProviderPatch, RunMessage
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.model import ScriptedModelProvider


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("user_id", ["user", "default_user"])
async def test_desktop_uses_standard_registered_execution_and_revision_recovery(tmp_path, monkeypatch, user_id):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(settings.model_copy(update={"component_selections": {
        **settings.component_selections,
        "agent.continuation-policy": "sage.agent.continuation.deterministic",
        "tool.selection-policy": "sage.tool-selection.direct",
        "memory.recall-query": "sage.memory.recall-query.direct",
    }}))
    await service.list_agents(user_id)
    await service.patch_model_provider("model_main", ModelProviderPatch(
        model="model-a", base_url="https://model.invalid/v1", api_keys=["secret"],
    ), user_id)
    agent = await service._agent("sage", user_id)
    await service.catalog.save_agent(agent.model_copy(update={"config": {
        **agent.config, "agentMode": "simple",
        "availableTools": ["file_read", "code.search", "plan.update", "process.run"],
        "availableSkills": [],
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
        ), user_id)]
        assert any(frame.get("type") == "run.completed" for frame in frames), frames
        handle = frames[0]["handle"]
        context = service._context(user_id)
        loaded = await cast('SAgentApplication', service.application).agent_for_run(handle["run_id"], context)
        command = await service.session_store.get_start_command(handle["run_id"])
        assert command.agent_id == loaded.id
        assert command.resolved_spec_hash == loaded.composition_hash
        assert (cast('Any', await cast('SAgentApplication', service.application).execution_configuration(handle["run_id"], context))).provider_id
    finally:
        await service.close()



@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,wrong_tenant", [("default_user", "default_user"), ("user", None), ("user", "other")])
async def test_desktop_run_plugin_rejects_a_mismatched_tenant(tmp_path, user_id, wrong_tenant):
    from app.v2.desktop.backend.sdk_plugins import desktop_run_inputs

    service = DesktopV2Service(tmp_path)
    context = service._context(user_id)
    actor = context.actor.model_copy(update={"tenant_id": wrong_tenant})
    run = SimpleNamespace(context=context.model_copy(update={"actor": actor}))
    dependencies = SimpleNamespace(require=lambda _: run)
    try:
        with pytest.raises(PermissionError, match="owner and tenant must match"):
            await desktop_run_inputs(service, None, dependencies)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_desktop_skill_visibility_reaches_the_model_request(tmp_path):
    from app.v2.desktop.backend.schemas import AgentSettingsPatch
    from sagents.v2.contracts.items import TextBlock
    from tests.app.v2.desktop.sdk_fixture import desktop, execute

    service, model, _ = desktop(tmp_path)
    try:
        inventory = await service.component_inventory("user_1")
        skill = next(item for item in inventory if item["component"]["component_id"] == "skill.loading")
        assert skill["contracts"]["skill.provider"]["module"] == "skill"
        provider = next(
            item for item in skill["contracts"]["skill.provider"]["implementations"]
            if item["id"] == "com.sage.desktop.run.skill-provider"
        )
        assert {"id": "skill.search", "status": "declared"} in provider["features"]
        for name in ("visible-guide", "searchable-guide"):
            folder = service.skill_root / name
            folder.mkdir()
            (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Guide\n---\nGuide body", encoding="utf-8")
        await service.list_agents("user_1")
        settings = await service.patch_agent_settings("sage", AgentSettingsPatch(
            available_tools=["search_skills"],
            available_skills=["visible-guide", "searchable-guide"],
            default_visible_skills=["visible-guide"],
            default_visible_skills_limit=25,
        ), "user_1")
        assert settings["default_visible_skills"] == ["visible-guide"]
        assert settings["default_visible_skills_limit"] == 25
        async def model_prompt():
            run, _, _ = await execute(service)
            assert run.state.value == "completed"
            request = model.requests[-1]
            prompt = "\n".join(
                block.text for message in request.messages if message.role == "system"
                for block in message.content if isinstance(block, TextBlock)
            )
            return {tool.name for tool in request.tools}, prompt

        tools, prompt = await model_prompt()
        assert {"search_skills", "load_skill"} <= tools
        assert "<skill_name>visible-guide</skill_name>" in prompt
        assert "<skill_name>searchable-guide</skill_name>" not in prompt

        await service.patch_agent_settings("sage", AgentSettingsPatch(available_tools=[]), "user_1")
        tools, prompt = await model_prompt()
        assert "search_skills" not in tools
        assert "<skill_name>visible-guide</skill_name>" in prompt
        assert "<skill_name>searchable-guide</skill_name>" not in prompt
        settings = await service.patch_agent_settings("sage", AgentSettingsPatch(
            available_skills=["searchable-guide"],
        ), "user_1")
        assert settings["default_visible_skills"] == []
        settings = await service.patch_agent_settings("sage", AgentSettingsPatch(
            default_visible_skills=None,
        ), "user_1")
        assert settings["default_visible_skills"] is None
    finally:
        await service.close()
