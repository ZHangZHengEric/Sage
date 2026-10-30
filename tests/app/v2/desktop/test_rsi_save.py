import base64
from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError

from app.v2.desktop.backend.app import create_app
from app.v2.desktop.backend.rsi_save import RsiSaveAs, save_rsi_version_as_agent
from app.v2.desktop.backend.schemas import (
    AgentCreate,
    AgentSettingsPatch,
    ModelProviderCreate,
    DesktopRunRequest,
    RunMessage,
)
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.tool.generated import generated_tool_provider
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.model.contracts import (
    ModelStreamEvent,
    ModelEventKind,
    ModelResponse,
    ModelToolCall,
)


async def candidate(service, user_id="alice"):
    provider = await service.create_model_provider(
        ModelProviderCreate(
            name="Offline",
            model="test",
            base_url="http://test.invalid/v1",
            api_keys=["test"],
        ),
        user_id,
    )
    result = await service.create_agent(
        AgentCreate(
            name="Original",
            settings=AgentSettingsPatch(
                llm_provider_id=provider["id"], available_tools=[], available_skills=[]
            ),
        ),
        user_id,
    )
    agent = await service._agent(result["id"], user_id)
    package = await service._agent_bundle(agent)
    data = package.model_dump(mode="json")
    data["manifest"]["agents"][agent.agent_id].update(
        instructions={"path": "prompts/system.md"},
        tools=["rsi_multiply"],
        skills=["verification"],
        budgets={"max_steps": 17},
    )
    data["files"].update(
        {
            "prompts/system.md": "Verify arithmetic before responding.",
            "skills/verification/SKILL.md": "---\nname: verification\ndescription: Verify results\n---\nCheck arithmetic.",
            "tools/rsi/rsi_multiply.json": json.dumps(
                {
                    "description": "Multiply",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "number"},
                            "b": {"type": "number"},
                        },
                        "required": ["a", "b"],
                    },
                    "expression": {"op": "mul", "args": [{"var": "a"}, {"var": "b"}]},
                }
            ),
        }
    )
    package = AgentPackageBundle.model_validate(data)
    version = {
        "id": "run-save.1",
        "source": "rsi",
        "ready": True,
        "name": agent.name,
        "config": deepcopy(agent.config),
        "package": package.model_dump(mode="json"),
        "package_hash": package.content_hash,
        "assets": {
            "skills/verification/example.bin": base64.b64encode(b"\x00\xff").decode()
        },
        "run_id": "run-save",
        "iteration": 1,
        "review": {"approved": True},
    }
    service.rsi_store.put(version, user_id, agent.agent_id, "version")
    return agent, version


@pytest.mark.asyncio
async def test_save_candidate_preserves_source_resources_and_survives_restart(
    tmp_path, monkeypatch
):
    service = DesktopV2Service(tmp_path)
    try:
        original, version = await candidate(service)
        request = RsiSaveAs(name=" Arithmetic specialist ", request_id="save-1")
        # Saving a frozen candidate must not depend on the source's current settings.
        await service.patch_agent_settings(
            original.agent_id, AgentSettingsPatch(system_prefix="New edit"), "alice"
        )
        current = await service._agent(original.agent_id, "alice")
        result = await save_rsi_version_as_agent(
            service, original.agent_id, version["id"], request, "alice"
        )
        saved = await service._agent(result["id"], "alice")
        assert saved.agent_id != original.agent_id
        assert saved.name == "Arithmetic specialist" and not saved.is_default
        assert saved.config["systemPrefix"] == "Verify arithmetic before responding."
        assert saved.config["maxLoopCount"] == 17
        assert saved.config["availableTools"] == ["rsi_multiply"]
        assert saved.config["availableSkills"] == ["verification"]
        assert saved.config["llm_provider_id"] == original.config["llm_provider_id"]
        assert saved.config["rsiAssets"] == version["assets"]
        package = AgentPackageBundle.model_validate(saved.config["rsiPackage"])
        assert package.manifest.entrypoint.agent == saved.agent_id
        assert set(package.manifest.agents) == {saved.agent_id}
        assert package.files == version["package"]["files"]
        assert [
            tool.name for tool in generated_tool_provider(package.files).definitions
        ] == ["rsi_multiply"]
        skill = await service._skill_provider(saved).fetch(
            "verification", run_id="save-test"
        )
        assert skill.files["example.bin"] == b"\x00\xff"
        assert (await service._agent(original.agent_id, "alice")) == current
        assert (
            service.rsi_store.get(version["id"], "alice", original.agent_id, "version")
            == version
        )
        assert saved.config["rsiOrigin"]["version_id"] == version["id"]
        again = await save_rsi_version_as_agent(
            service, original.agent_id, version["id"], request, "alice"
        )
        assert again["id"] == saved.agent_id
        with pytest.raises(ValueError, match="different parameters"):
            await save_rsi_version_as_agent(
                service,
                original.agent_id,
                version["id"],
                RsiSaveAs(name="Different", request_id="save-1"),
                "alice",
            )
    finally:
        await service.close()
    restored = DesktopV2Service(tmp_path)
    try:
        assert (await restored._agent(saved.agent_id, "alice")).config == saved.config
        assert (await restored.rsi_history(saved.agent_id, "alice"))["runs"] == []
        assert (await restored._agent(original.agent_id, "alice")) == current
        model = ScriptedModelProvider(
            tuple(
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED, response=response
                        ),
                    )
                )
                for response in (
                    ModelResponse(
                        response_id="multiply",
                        tool_calls=(
                            ModelToolCall(
                                tool_call_id="multiply",
                                name="rsi_multiply",
                                arguments={"a": 6, "b": 7},
                            ),
                        ),
                        finish_reason="tool_calls",
                    ),
                    ModelResponse(
                        response_id="answer", text="42", finish_reason="stop"
                    ),
                )
            )
        )

        async def bind(*args, **kwargs):
            return model

        monkeypatch.setattr(restored, "_model_provider", bind)
        settings = await restored.get_settings()
        await restored.save_settings(
            settings.model_copy(
                update={
                    "component_selections": {
                        **settings.component_selections,
                        "tool.selection-policy": "sage.tool-selection.direct",
                        "agent.continuation-policy": "sage.agent.continuation.deterministic",
                    }
                }
            )
        )
        frames = [
            json.loads(frame)
            async for frame in restored.run_events(
                DesktopRunRequest(
                    agent_id=saved.agent_id,
                    messages=[RunMessage(role="user", text="6 times 7?")],
                    idempotency_key="saved-agent-tool-test",
                    run_context={
                        "model_provider_id": saved.config["llm_provider_id"],
                        "fast_model_provider_id": saved.config["llm_provider_id"],
                    },
                ),
                "alice",
            )
        ]
        results = [
            frame.get("data", {}).get("item", {}).get("data", {}) for frame in frames
        ]
        assert any(
            item.get("kind") == "tool_result"
            and item.get("tool_call_id") == "multiply"
            and not item.get("error")
            and any(block.get("text") == "42" for block in item.get("content", []))
            for item in results
        ), results
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_save_rejects_unready_rejected_and_unowned_versions(tmp_path):
    service = DesktopV2Service(tmp_path)
    try:
        agent, version = await candidate(service)
        request = RsiSaveAs(name="New", request_id="save-1")
        before = await service.catalog.list_agents("alice")
        with pytest.raises(ValueError, match="not configured"):
            await save_rsi_version_as_agent(
                service, agent.agent_id, version["id"], request, "bob"
            )
        for changes, error in (
            ({"ready": False}, "not complete"),
            ({"review": {"approved": False}}, "rejected"),
        ):
            service.rsi_store.put(
                {**version, **changes}, "alice", agent.agent_id, "version"
            )
            with pytest.raises(ValueError, match=error):
                await save_rsi_version_as_agent(
                    service, agent.agent_id, version["id"], request, "alice"
                )
        assert await service.catalog.list_agents("alice") == before
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_save_http_auth_validation_and_retry(tmp_path):
    service = DesktopV2Service(tmp_path)
    try:
        agent, version = await candidate(service, "default_user")
        app = create_app(service=service, auth_token="local-save")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/api/v2/agents/{agent.agent_id}/rsi/versions/{version['id']}/save-as-agent"
            body = {"name": "Saved", "request_id": "http-1"}
            assert (await client.post(path, json=body)).status_code == 401
            headers = {"Authorization": "Bearer local-save"}
            assert (
                await client.post(path, headers=headers, json={**body, "name": "  "})
            ).status_code == 422
            first = await client.post(path, headers=headers, json=body)
            second = await client.post(path, headers=headers, json=body)
            assert first.status_code == second.status_code == 200
            assert first.json()["data"]["id"] == second.json()["data"]["id"]
    finally:
        await service.close()


def test_save_name_validation():
    with pytest.raises(ValidationError):
        RsiSaveAs(name=" ", request_id="save")
