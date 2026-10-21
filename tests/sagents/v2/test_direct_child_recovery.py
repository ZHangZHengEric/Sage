"""Resume a paused nested child through public APIs, with ancestors still paused."""

from typing import cast

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

import asyncio

import pytest

from sagents.v2.contracts.commands import PauseRun, ResumeRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.binding import ExecutionBindingRequest
from sagents.v2.runtime.execution.recovery import acquire_execution_binding
from tests.sagents.v2.test_builder_nested_teams import (
    Models,
    delegate,
    environment,
    load_tree,
    open_app,
    run,
)
from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True], ids=["same-app", "restart"])
async def test_leaf_resume_rebuilds_ancestor_resources_without_running_ancestors(
    tmp_path, restart
):
    arrived = asyncio.Queue()
    release = asyncio.Event()
    phase = "before"
    seen = {"before": set(), "after": set()}
    environments = []

    class PausingModels(Models):
        def factory(self, context, dependencies):
            model = super().factory(context, dependencies)
            role = context.agent_configuration["execution_agent_id"]
            role = "root" if role == "assistant" else role

            class PausingModel:
                capabilities = model.capabilities

                async def stream(self, request):
                    text = "\n".join(
                        getattr(block, "text", "")
                        for message in request.messages
                        for block in message.content
                    )
                    local_role = role.rsplit(".", 1)[-1]
                    assert f"PRELOAD {local_role}" in text
                    assert f"{local_role} original" in text
                    seen[phase].add(role)
                    environments.append((phase, role, environment(request)))
                    if role == "director.maker" and not release.is_set():
                        await arrived.put(request.run_id)
                        await release.wait()
                    async for event in model.stream(request):
                        yield event

            return PausingModel()

    models = PausingModels(
        {
            "root": (delegate("director"),),
            "director": (delegate("maker"),),
            "director.maker": (
                (
                    "file_write",
                    {"file_path": "result.txt", "content": "recovered leaf"},
                ),
            ),
        }
    )
    app, bindings, _ = await open_app(tmp_path, models)
    task = None
    try:
        root = await load_tree(app)
        task = asyncio.create_task(run(app, root))
        leaf = await asyncio.wait_for(arrived.get(), 15)
        access = app.service("session.access")
        director = (await access.get_start_command(leaf, CONTEXT)).parent_run_id
        root_id = (await access.get_start_command(director, CONTEXT)).parent_run_id
        ids = (leaf, director, root_id)
        originals = {}
        for target in ids:
            snapshot = await access.get_run(target, CONTEXT)
            originals[target] = (
                snapshot.session_id,
                await app.execution_configuration(target, CONTEXT),
            )
            receipt = await app.runtime.pause_run(
                PauseRun(
                    run_id=target,
                    expected_revision=snapshot.revision,
                    idempotency_key=f"pause-{target}",
                ),
                CONTEXT,
            )
            assert receipt.decision.value == "accepted"
        release.set()
        result, _ = await asyncio.wait_for(task, 15)
        assert result.state.value == "suspended"
        if restart:
            await app.close()
            await bindings.close()
            app, bindings, _ = await open_app(tmp_path, models)
        leaf_command = await app.service("session.access").get_start_command(
            leaf, CONTEXT
        )
        with pytest.raises(SageV2Error) as missing:
            await bindings.acquire(
                ExecutionBindingRequest(
                    run_id=leaf,
                    parent_run_id=director,
                    agent_id=leaf_command.agent_id,
                    context=CONTEXT,
                    configuration=leaf_command.config.execution_snapshot,
                )
            )
        assert missing.value.info.code == "execution.parent_binding_not_ready"
        assert missing.value.info.safe_to_resume and missing.value.info.retryable
        # Fault injection at the binding protocol boundary: a corrupted leaf
        # snapshot must roll back resource-only ancestor acquisitions.
        with pytest.raises(SageV2Error) as corrupt:
            await acquire_execution_binding(
                bindings,
                ExecutionBindingRequest(
                    run_id=leaf,
                    parent_run_id=director,
                    agent_id=leaf_command.agent_id,
                    context=CONTEXT,
                    configuration=leaf_command.config.execution_snapshot.model_copy(
                        update={"configuration_id": "corrupted"}
                    ),
                ),
                app.runtime,
            )
        assert corrupt.value.info.code == "execution.configuration_incompatible"
        assert not [binding for binding in bindings.bindings if not binding.closed]
        phase = "after"
        for index, target in enumerate(ids):
            access = app.service("session.access")
            snapshot = await access.get_run(target, CONTEXT)
            assert snapshot.state.value == "suspended"
            # Merely loading the original revision must not execute ancestors.
            agent = await app.agent_for_run(target, CONTEXT)
            suspension = await app.runtime.session_store.get_suspension(
                snapshot.suspension_id
            )
            receipt = await app.runtime.resume_run(
                ResumeRun(
                    run_id=target,
                    expected_revision=snapshot.revision,
                    idempotency_key=f"resume-{target}",
                    suspension_id=suspension.suspension_id,
                    expected_suspension_revision=suspension.expected_revision,
                ),
                CONTEXT,
            )
            assert receipt.decision.value == "accepted"
            future = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(target, CONTEXT, agent=agent)
            completed = await asyncio.wait_for(future, 15)
            assert completed.state.value == "completed", completed
            facts = await app.execution_diagnostics(target, CONTEXT)
            dependencies = facts["resource_dependencies"]
            assert [item["run_id"] for item in dependencies] == list(
                reversed(ids[index + 1 :])
            )
            assert {item["sandbox"]["sandbox_id"] for item in dependencies} <= {
                facts["sandbox"]["sandbox_id"]
            }
            for item in dependencies:
                assert item["sandbox"]["owner_run_id"] == item["run_id"]
                ancestor_facts = await app.execution_diagnostics(
                    item["run_id"], CONTEXT
                )
                assert (
                    ancestor_facts["sandbox"]["sandbox_id"]
                    == facts["sandbox"]["sandbox_id"]
                )
            assert facts["sandbox"]["owner_run_id"] == target
            assert completed.run_id == target
            assert completed.session_id == originals[target][0]
            assert (
                await app.execution_configuration(target, CONTEXT)
                == originals[target][1]
            )
            assert seen["after"] == set(
                ("director.maker", "director", "root")[: index + 1]
            )
            for ancestor in ids[index + 1 :]:
                assert (
                    await access.get_run(ancestor, CONTEXT)
                ).state.value == "suspended"
        assert (tmp_path / "workspace" / "result.txt").read_text() == "recovered leaf"
        # The original delegation calls were settled, not dispatched again.
        for target in ids:
            events = await access.read_events(target, CONTEXT)
            calls = [event for event in events if event.type == "tool.call.started"]
            assert len(calls) == 1, calls
            session_runs = await access.list_session_runs(originals[target][0], CONTEXT)
            assert [value.run_id for value in session_runs] == [target]
        assert not [binding for binding in bindings.bindings if not binding.closed]
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await app.close()
        await bindings.close()
