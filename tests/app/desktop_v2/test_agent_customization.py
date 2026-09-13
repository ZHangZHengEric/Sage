import asyncio
import pytest
from app.desktop_v2.backend.service import DesktopV2Service
from app.desktop_v2.backend.schemas import AgentCreate, AgentSettingsPatch


@pytest.mark.asyncio
async def test_clone_full_configuration_is_independent_and_invalid_create_is_atomic(tmp_path):
    service = DesktopV2Service(tmp_path)
    try:
        original = await service.create_agent(AgentCreate(name="Original", settings=AgentSettingsPatch(
            description="Expert", system_prefix="Verify units", max_loop_count=750,
            runtime_variables={"style": "precise"})), "user_1")
        clone = await service.create_agent(AgentCreate(name="Copy", source_agent_id=original["id"]), "user_1")
        assert clone["id"] != original["id"]
        for field in ("description", "system_prefix", "max_loop_count", "runtime_variables", "available_tools"):
            assert clone[field] == original[field]
        await service.patch_agent_settings(clone["id"], AgentSettingsPatch(description="Changed"), "user_1")
        assert (await service.get_agent_settings(original["id"], "user_1"))["description"] == "Expert"
        count = len(await service.list_agents("user_1"))
        with pytest.raises(ValueError, match="unknown"):
            await service.create_agent(AgentCreate(name="Invalid", settings=AgentSettingsPatch(available_tools=["missing-tool"])), "user_1")
        assert len(await service.list_agents("user_1")) == count
        agent = await service._agent(original["id"], "user_1")
        provider = await service.catalog.get_model_provider(original["llm_provider_id"], "user_1")
        manifest = service._manifest(agent, provider, (), ())
        assert manifest.agents[manifest.entrypoint.agent].budgets.max_steps == 750
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_concurrent_agent_patches_merge_different_fields(tmp_path):
    service = DesktopV2Service(tmp_path)
    try:
        agent = await service.create_agent(AgentCreate(name="Original"), "user_1")
        await asyncio.gather(
            service.patch_agent_settings(agent["id"], AgentSettingsPatch(description="Expert"), "user_1"),
            service.patch_agent_settings(agent["id"], AgentSettingsPatch(system_prefix="Check facts"), "user_1"),
        )
        result = await service.get_agent_settings(agent["id"], "user_1")
        assert result["description"] == "Expert"
        assert result["system_prefix"] == "Check facts"
    finally:
        await service.close()
