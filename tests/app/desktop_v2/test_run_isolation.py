import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.desktop_v2.backend.catalog import DesktopMcpRecord
from app.desktop_v2.backend.schemas import (
    DesktopMcpBinding,
    DesktopRunContext,
    DesktopRunRequest,
    ModelProviderPatch,
    RunMessage,
)
from app.desktop_v2.backend.service import DesktopV2Service
from examples.sagents_v2_multi_project import ConcurrentModel
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime.session import FilesystemSessionStore


async def change_context(service, marker):
    agent = await service._agent("sage", "user")
    await service.catalog.save_agent(
        agent.model_copy(
            update={
                "config": {**agent.config, "systemContext": {"project_marker": marker}}
            }
        )
    )


async def configure(service, root):
    await service.list_agents("user")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            model="model-a",
            base_url="https://model.invalid/v1",
            api_keys=["secret-key"],
        ),
        "user",
    )
    original = await service.catalog.get_model_provider("model_main", "user")
    await service.catalog.save_model_provider(
        original.model_copy(update={"id": "model_b", "model": "model-b"})
    )
    agent = await service._agent("sage", "user")
    await service.catalog.save_agent(
        agent.model_copy(
            update={
                "config": {
                    **agent.config,
                    "agentMode": "simple",
                    "availableTools": ["mcp_project_write"],
                    "availableSkills": [],
                }
            }
        )
    )
    await service.catalog.save_mcp(
        DesktopMcpRecord(
            user_id="user",
            name="project",
            protocol="stdio",
            command="fake-mcp",
            env={"PRIVATE_TOKEN": "catalog-secret"},
        )
    )
    projects = {}
    for key in ("a", "b"):
        path = root / key
        path.mkdir()
        projects[key] = await service.add_project(key, str(path))
    return projects


def request(project, session, model="model_main"):
    return DesktopRunRequest(
        agent_id="sage",
        session_id=session,
        workspace_id=project.id,
        messages=[RunMessage(role="user", text="write artifacts")],
        approval_mode="auto_approve",
        idempotency_key=session,
        run_context=DesktopRunContext(
            model_provider_id=model,
            system_context={"project_marker": session},
            mcp_bindings=[
                DesktopMcpBinding(
                    name="project", env={"DIRECTORY": project.path, "SESSION": session}
                )
            ],
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("same_project", [False, True])
@pytest.mark.parametrize("first_action", ["complete", "cancel", "approve"])
async def test_desktop_runs_overlap_and_keep_model_context_and_mcp_directory(
    tmp_path,
    monkeypatch,
    same_project,
    first_action,
):
    cancel_first = first_action == "cancel"
    service = DesktopV2Service(tmp_path / "service")
    projects = await configure(service, tmp_path)
    model = ConcurrentModel(service.session_store)
    writes = []

    @asynccontextmanager
    async def transport(config):
        async def list_tools():
            return {
                "tools": [
                    {
                        "name": "write",
                        "description": "write artifact",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"round": {"type": "integer"}},
                            "required": ["round"],
                        },
                    }
                ]
            }

        async def call_tool(name, arguments):
            path = (
                Path(config.env["DIRECTORY"])
                / f"{config.env['SESSION']}-{arguments['round']}.txt"
            )
            path.write_text(config.env["SESSION"])
            writes.append(path)
            await asyncio.sleep(0)
            return {"content": [{"type": "text", "text": str(path)}]}

        yield SimpleNamespace(list_tools=list_tools, call_tool=call_tool)

    monkeypatch.setattr("sagents.v2.tool.plugins.mcp._sdk_session", transport)

    async def provider_factory(provider, agent, **kwargs):
        async def stream(value):
            command = await service.session_store.get_start_command(value.run_id)
            assert command.config.metadata["model_route"]["model"] == provider.model
            model.entered.add(value.run_id)
            if len(model.entered) == 2:
                model.all_started.set()
            async for event in model.stream(value):
                yield event

        return SimpleNamespace(capabilities=model.capabilities, stream=stream)

    monkeypatch.setattr(service, "_model_provider", provider_factory)
    building = set()
    both_building = asyncio.Event()
    release_build = asyncio.Event()
    original_build = service._build_loop

    async def delayed_build(**kwargs):
        building.add(kwargs["run_id"])
        if len(building) == 2:
            both_building.set()
        await release_build.wait()
        return await original_build(**kwargs)

    monkeypatch.setattr(service, "_build_loop", delayed_build)
    requests = [
        request(projects["a"], "session-a"),
        request(projects["a" if same_project else "b"], "session-b", "model_b"),
    ]
    if first_action == "approve":
        requests[0].approval_mode = "always_ask"

    async def collect(value):
        return [json.loads(frame) async for frame in service.run_events(value, "user")]

    tasks = [asyncio.create_task(collect(value)) for value in requests]
    try:
        await asyncio.wait_for(both_building.wait(), timeout=15)
        # Change catalog inputs AFTER admission, BEFORE lazy driver composition.
        await service.patch_model_provider(
            "model_main", ModelProviderPatch(model="changed"), "user"
        )
        await change_context(service, "wrong")
        await service.catalog.save_mcp(
            DesktopMcpRecord(
                user_id="user",
                name="project",
                protocol="stdio",
                command="wrong",
                env={"DIRECTORY": str(tmp_path / "wrong"), "SESSION": "wrong"},
            )
        )
        release_build.set()
        await asyncio.wait_for(model.all_started.wait(), timeout=15)
        if cancel_first:
            runs = await service.session_runs("session-a", "user")
            await service.cancel(runs[0]["run_id"], "user")
        model.release.set()
        frames = await asyncio.wait_for(asyncio.gather(*tasks), timeout=20)
        if first_action == "approve":
            assert any(frame.get("type") == "run.completed" for frame in frames[1])
            assert len(writes) == 3  # B completed while A remained suspended.
            run_id = frames[0][0]["handle"]["run_id"]
            for _ in range(3):
                run = await service.session_store.get_run(run_id)
                assert run.state.value == "suspended"
                suspension = await service.session_store.get_suspension(
                    run.suspension_id
                )
                # Force real driver recomposition on each approval boundary.
                driver = service._drivers.get(run_id)
                if driver is not None:
                    await service._discard_driver_if_terminal(run_id, driver)
                await service.reply_interaction(
                    run_id, suspension.interaction_id, "approve_once", {}, "user"
                )

                async def resumed_frames():
                    return [
                        json.loads(frame)
                        async for frame in service.subscribe_events(
                            run_id, run.last_run_sequence, "user"
                        )
                    ]

                frames[0].extend(await asyncio.wait_for(resumed_frames(), timeout=15))
        for index, rows in enumerate(frames):
            terminal = (
                "run.cancelled" if index == 0 and cancel_first else "run.completed"
            )
            assert any(frame.get("type") == terminal for frame in rows), frames
        assert len(writes) == (3 if cancel_first else 6)
        for value in requests:
            directory = next(
                project.path
                for project in projects.values()
                if project.id == value.workspace_id
            )
            if cancel_first and value.session_id == "session-a":
                assert not list(Path(directory).glob("session-a-*.txt"))
                continue
            for index in range(3):
                assert (
                    Path(directory) / f"{value.session_id}-{index}.txt"
                ).read_text() == value.session_id
        assert not (tmp_path / "wrong").exists()
    finally:
        release_build.set()
        model.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()


@pytest.mark.asyncio
async def test_environment_snapshot_recovery_and_child_use_original_inputs(tmp_path):
    service = DesktopV2Service(tmp_path / "service")
    projects = await configure(service, tmp_path)
    value = request(projects["a"], "session-a")
    environment = await service._capture_run_environment(value, "user")
    command = StartRun(
        agent_id="sage",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        config=RunConfig(metadata={"desktop_environment": environment.snapshot}),
        resolved_spec_hash="sha256:test",
        idempotency_key="parent",
    )
    parent = await service.runtime.start_run(command, service._context("user"))
    service._run_environments[parent.run_id] = environment
    child = command.model_copy(
        update={
            "parent_run_id": parent.run_id,
            "config": RunConfig(),
            "idempotency_key": "child",
        }
    )
    # Mutating caller inputs and catalog cannot mutate the captured objects.
    value.run_context.system_context["project_marker"] = "changed"
    await change_context(service, "changed")
    assert (
        await service._environment_for_command(child, "user", "child-id")
    ) is environment
    assert (
        environment.agents["sage"].config["systemContext"]["project_marker"]
        == "session-a"
    )
    assert "secret-key" not in json.dumps(environment.snapshot)
    assert "catalog-secret" not in json.dumps(environment.snapshot)
    await service.remove_project(projects["a"].id)
    await service.close()
    service = DesktopV2Service(tmp_path / "service")
    restored = await service._environment_for_command(child, "user", "child-id")
    assert restored.workspace == Path(projects["a"].path)
    assert (
        restored.agents["sage"].config["systemContext"]["project_marker"] == "session-a"
    )
    current = await service.catalog.get_agent("sage", "user")
    await service.catalog.save_agent(
        current.model_copy(
            update={
                "config": {
                    **current.config,
                    "approvedShellCommands": ["git status"],
                }
            }
        )
    )
    continued = await service._agent_in_environment(command, restored, "user")
    assert continued.config["approvedShellCommands"] == ["git status"]
    assert continued.config["systemContext"]["project_marker"] == "session-a"
    service._run_environments.clear()
    await service.catalog.save_mcp(
        DesktopMcpRecord(
            user_id="user", name="project", protocol="stdio", command="changed"
        )
    )
    with pytest.raises(ValueError, match="MCP configuration changed"):
        await service._environment_for_command(child, "user", "child-id")
    await service.close()


@pytest.mark.asyncio
async def test_borrowed_store_survives_service_close(tmp_path):
    store = FilesystemSessionStore(tmp_path / "shared")
    close = store.close
    store.close = AsyncMock(wraps=close)
    service = DesktopV2Service(tmp_path / "desktop", session_store=store)
    await service.start()
    await service.close()
    store.close.assert_not_awaited()
    await store.list_dispatchable_runs()
    await store.close()


@pytest.mark.asyncio
async def test_run_overrides_reject_unknown_models_and_expanded_tools(tmp_path):
    service = DesktopV2Service(tmp_path / "service")
    projects = await configure(service, tmp_path)
    with pytest.raises(ValueError, match="model provider is unavailable"):
        await service._capture_run_environment(
            request(projects["a"], "one", "missing"), "user"
        )
    value = request(projects["a"], "two")
    value.run_context.tools = ["file_write"]
    with pytest.raises(ValueError, match="exceed"):
        await service._capture_run_environment(value, "user")
    agent = await service._agent("sage", "user")
    await service.catalog.save_agent(
        agent.model_copy(
            update={
                "config": {
                    **agent.config,
                    "availableSkills": ["example-skill"],
                }
            }
        )
    )
    value.run_context.tools = []
    environment = await service._capture_run_environment(value, "user")
    assert environment.agents["sage"].config["availableTools"] == []
    assert environment.agents["sage"].config["availableSkills"] == []
    await service.close()
