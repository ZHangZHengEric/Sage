
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.application import SAgentApplication
    from sagents.v2.package.manifest.agents import AgentMemoryBehavior

import asyncio
import pytest
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.schemas import AgentCreate, AgentSettingsPatch


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
        assert getattr(manifest.agents[cast('str', manifest.entrypoint.agent)], 'budgets').max_steps == 750
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


@pytest.mark.asyncio
@pytest.mark.parametrize('recall,auto_write,scope', [(False, False, 'agent'), (True, False, 'session'), (False, True, 'principal')])
async def test_explicit_memory_settings_survive_clone_and_drive_runtime(tmp_path, recall, auto_write, scope):
    from app.v2.desktop.backend.schemas import ModelProviderPatch
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, _, _ = desktop(tmp_path)
    try:
        created = await service.create_agent(AgentCreate(name='Memory', settings=AgentSettingsPatch(
            available_tools=['search_memory'], available_skills=[],
            memory=cast('AgentMemoryBehavior | None', {'recall': recall, 'auto_write': auto_write, 'scope': scope}),
        )), 'user_1')
        assert created['memory'] == {'recall': recall, 'auto_write': auto_write, 'scope': scope}
        clone = await service.create_agent(AgentCreate(name='Clone', source_agent_id=created['id']), 'user_1')
        assert clone['memory'] == created['memory']
        await service.patch_model_provider('model_main', ModelProviderPatch(api_keys=['test-key']), 'user_1')
        agent = await service._agent(created['id'], 'user_1')
        provider = await service._provider(agent, 'user_1')
        run, command, _ = await execute(service, agent_id=agent.agent_id)
        assert run.state.value == "completed"
        accepted = await cast('SAgentApplication', service.application).run_configuration(run.run_id, service._context("user_1"))
        assert accepted["agent"]["memory"]["recall"] is recall
        assert service._memory_service_for_agent(agent).scope_mode == scope
        manifest = service._manifest(agent, provider, ('search_memory',), ())
        behavior = manifest.agents[agent.agent_id].memory
        assert behavior.model_dump() == created['memory']
        # Changing unrelated fields must retain the persisted memory choices.
        updated = await service.patch_agent_settings(agent.agent_id, AgentSettingsPatch(description='Changed'), 'user_1')
        assert updated['memory'] == created['memory']
    finally:
        await service.close()
