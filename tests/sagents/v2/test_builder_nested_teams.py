"""Public Builder regressions: frozen, scoped nested Teams and Run leases."""

from __future__ import annotations
from tests.sagents.v2.sdk_fixture import build_registered_app

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.composition.defaults import default_runtime
from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.runtime.execution import LocalWorkspaceExecutionBindingProvider
from sagents.v2.runtime.execution.sandbox import SandboxState
from sagents.v2.skill import InMemorySkillProvider, InMemorySkillWorkspace
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT
from tests.sagents.v2.test_skill_provider_matrix import bundle


def package(role, children=(), *, version="original"):
    value = BuiltinPackageFactory.create("assistant", package_id="test.nested." + role)
    definition = value.agents["assistant"]
    definition = definition.model_copy(
        update={
            "mode": "team" if children else "simple",
            "subagents": tuple(children),
            "tools": ("file_read",) if children else ("file_write",),
            "models": {"primary": role + ("-changed" if version == "changed" else "")},
            "delegation_model_bindings": {
                "primary": role + ("-changed" if version == "changed" else "")
            },
            "skills": (role + "-skill",),
            "preload_skills": (role + "-skill",),
            "instructions": definition.instructions.model_copy(
                update={"inline": role + " " + version}
            ),
        }
    )
    return value.model_copy(update={"agents": {"assistant": definition}})


class Models:
    def __init__(self, plans):
        self.plans = plans
        self.seen = []
        self.observe = lambda role, request: None

    def factory(self, context, dependencies):
        agent_id = context.agent_configuration["execution_agent_id"]
        role = (
            context.agent_configuration["package_id"].rsplit(".", 1)[-1]
            if agent_id == "assistant"
            else agent_id
        )
        owner = self

        class Model:
            async def capabilities(self, binding):
                return ModelCapabilities(
                    supports_streaming=True,
                    supports_tools=True,
                    supports_parallel_tool_calls=True,
                    supports_reasoning=False,
                    supports_multimodal_input=False,
                    supports_structured_output=False,
                )

            async def stream(self, request):
                owner.observe(role, request)
                owner.seen.append((role, request))
                # Count only this scripted model's calls, including restored history.
                stage = sum(
                    len(m.tool_calls) for m in request.messages if m.role == "assistant"
                )
                plan = owner.plans.get(role, ())
                call = plan[stage] if stage < len(plan) else None
                if callable(call):
                    call = call(request)
                calls = (
                    (
                        ModelToolCall(
                            tool_call_id=f"{request.run_id}-{stage}",
                            name=call[0],
                            arguments=call[1],
                        ),
                    )
                    if call
                    else ()
                )
                yield ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(
                        response_id=f"{request.run_id}-{stage}",
                        text="" if calls else "done",
                        tool_calls=calls,
                        finish_reason="tool_calls" if calls else "stop",
                    ),
                )

        return Model()


def delegate(*agents):
    return "sys_team_delegate_task", {
        "tasks": [{"agent_id": name, "content": "make result"} for name in agents]
    }


def environment(request):
    for message in request.messages:
        for block in message.content:
            text = getattr(block, "text", "")
            if "<sandbox_environment>\n" in text:
                return json.loads(
                    text.split("<sandbox_environment>\n", 1)[1].split(
                        "</sandbox_environment>", 1
                    )[0]
                )
    raise AssertionError("missing sandbox context")


async def open_app(tmp_path, models, *, approval=False):
    bindings = LocalWorkspaceExecutionBindingProvider(
        tmp_path / "workspace", process_enabled=False
    )
    runtime = default_runtime(tmp_path / "sessions")
    runtime = runtime.model_copy(
        update={
            "capabilities": {
                **runtime.capabilities,
                "tool.provider": CapabilitySelection(plugin="sage.tool.official"),
                "tool.selection-policy": CapabilitySelection(
                    plugin="sage.tool-selection.direct"
                ),
                "agent.continuation-policy": CapabilitySelection(
                    plugin="sage.agent.continuation.deterministic"
                ),
            }
        }
    )
    skills = InMemorySkillProvider(
        tuple(
            bundle(role + "-skill", "PRELOAD " + role)
            for role in ("root", "director", "maker", "outsider", "d1", "d2")
        )
    )

    class Policy(DefaultToolPolicy):
        async def decide(self, context):
            if approval and context.definition.name == "file_write":
                return await DefaultToolPolicy(
                    approval_strategy=ApprovalStrategy.ALWAYS_ASK
                ).decide(context)
            return await super().decide(context)

    app = await (
        build_registered_app(tmp_path / 'sessions', models={**TEST_MODELS, 'models': {**TEST_MODELS['models'], **{name + suffix: TEST_MODELS['models']['primary'] for name in ('root', 'director', 'maker', 'outsider', 'd1', 'd2') for suffix in ('', '-changed')}}}, model_factory=models.factory, skills=(skills, skills, InMemorySkillWorkspace(),), runtime=runtime, providers={'execution.binding': bindings, 'agent.tool-policy': Policy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)})
    )
    return app, bindings, skills


async def load_tree(app, *, version="original"):
    maker = await app.load_agent(package("maker", version=version))
    director = await app.load_agent(
        package("director", ("maker",), version=version), subagents={"maker": maker}
    )
    outsider = await app.load_agent(package("outsider"))
    root = await app.load_agent(
        package("root", ("director", "outsider")),
        subagents={"director": director, "outsider": outsider},
    )
    return root


async def run(app, root, *, config=None):
    stream = await app.entrypoint().run_stream(
        StartRun(
            agent_id=root.id,
            resolved_spec_hash=root.composition_hash,
            idempotency_key="nested",
            config=config or RunConfig(),
            input=(InputItem(role="user", content=(TextBlock(text="delegate"),)),),
        ),
        CONTEXT,
        agent=root,
    )
    async with asyncio.timeout(60):
        events = [event async for event in stream.events]
        result = await stream.wait()
    return result, events


@pytest.mark.asyncio
async def test_public_builder_nested_rosters_preloads_and_shared_leases(tmp_path):
    models = Models(
        {
            # Reject grandchild bypass, then continue with the declared Team.
            "root": (
                delegate("director.maker"),
                delegate("director"),
                ("file_read", {"file_path": "result.txt"}),
            ),
            # Neither an ancestor nor a sibling belongs to director's roster.
            "director": (
                delegate("assistant"),
                delegate("outsider"),
                delegate("maker"),
            ),
            "director.maker": (
                ("file_write", {"file_path": "result.txt", "content": "nested result"}),
            ),
        }
    )
    app, bindings, skills = await open_app(tmp_path, models)
    try:
        root = await load_tree(app)

        def observe(role, request):
            row = next(iter(bindings.sandbox_provider._rows.values()))
            if role == "director.maker":
                assert len(row.members) == 3
                assert all(not m.lease_terminated for m in row.members.values())
            elif role == "root" and len(row.members) == 3:
                # Director and maker finished; root still reads the shared file.
                assert sum(not m.lease_terminated for m in row.members.values()) == 1

        models.observe = observe
        result, events = await run(app, root)
        assert result.state.value == "completed", [
            (e.type, e.data) for e in events if e.type.endswith("failed")
        ]
        assert (tmp_path / "workspace/result.txt").read_text() == "nested result"
        requests = dict(models.seen)
        assert set(requests) == {"root", "director", "director.maker"}
        assert all(
            "sys_team_delegate_task" in {t.name for t in requests[r].tools}
            for r in ("root", "director")
        )
        assert "sys_team_delegate_task" not in {
            t.name for t in requests["director.maker"].tools
        }
        for role, request in models.seen:
            local = "maker" if role == "director.maker" else role
            text = request.model_dump_json()
            assert "PRELOAD " + local in text
            assert local + " original" in text
            assert request.model_binding == ("primary" if role == "root" else local)
        failures = [e for e in events if e.type == "tool.call.failed"]
        assert (
            failures
        )  # Root rejected a grandchild; director failures live in its own Run.
        envs = [environment(request) for _, request in models.seen]
        assert len({e["sandbox_id"] for e in envs}) == 1
        assert len({e["lease_owner_run_id"] for e in envs}) == 3
        row = next(iter(bindings.sandbox_provider._rows.values()))
        assert len(row.members) == 3
        assert all(member.lease_terminated for member in row.members.values())
        assert row.state == SandboxState.TERMINATED
        assert {name for _, name in skills.fetches} == {
            "root-skill",
            "director-skill",
            "maker-skill",
        }
        director_run = requests["director"].run_id
        child_events = await app.runtime.session_store.read_events(director_run)
        assert len([e for e in child_events if e.type == "tool.call.failed"]) == 2
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_public_builder_parallel_nested_teams_do_not_exhaust_parent_slots(
    tmp_path,
):
    plans = {"root": (delegate("d1", "d2"),)}
    for name in ("d1", "d2"):
        plans[name] = (delegate("maker"),)
        plans[name + ".maker"] = (
            ("file_write", {"file_path": name + ".txt", "content": name}),
        )
    models = Models(plans)
    app, bindings, _ = await open_app(tmp_path, models)
    try:
        maker = await app.load_agent(package("maker"))
        children = {
            name: await app.load_agent(
                package(name, ("maker",)), subagents={"maker": maker}
            )
            for name in ("d1", "d2")
        }
        root = await app.load_agent(package("root", ("d1", "d2")), subagents=children)
        result, _ = await run(app, root)
        assert result.state.value == "completed"
        assert (tmp_path / "workspace/d1.txt").read_text() == "d1"
        assert (tmp_path / "workspace/d2.txt").read_text() == "d2"
    finally:
        await app.close()
        await bindings.close()


def restart_plans():
    return {
        "root": (delegate("director"),),
        "director": (delegate("maker"),),
        "director.maker": (
            ("file_write", {"file_path": "restored.txt", "content": "original"}),
        ),
    }


async def pause_nested(tmp_path):
    models = Models(restart_plans())
    app, bindings, _ = await open_app(tmp_path, models, approval=True)
    try:
        root = await load_tree(app)
        result, _ = await run(app, root)
        assert result.state.value == "suspended"
        run_id, frozen_hash = result.run_id, root.composition_hash
        assert not (tmp_path / "workspace/restored.txt").exists()
    finally:
        await app.close()
        await bindings.close()
    (tmp_path / "paused.json").write_text(
        json.dumps({"run_id": run_id, "hash": frozen_hash})
    )


async def resume_nested(tmp_path):
    paused = json.loads((tmp_path / "paused.json").read_text())
    run_id, frozen_hash = paused["run_id"], paused["hash"]
    # Brand new application, models and sandbox provider; no cached child loops.
    models = Models(restart_plans())
    app, bindings, _ = await open_app(tmp_path, models, approval=True)
    try:
        latest = await load_tree(app, version="changed")
        restored = await app.agent_for_run(run_id, CONTEXT)
        assert restored.composition_hash == frozen_hash != latest.composition_hash
        state = await app.runtime.get_run(run_id)
        store = app.runtime.session_store
        suspension = await store.get_suspension(state.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        await app.runtime.reply_interaction(
            ReplyInteraction(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction.interaction_id,
                expected_revision=state.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision="approve_once",
                idempotency_key="resume-nested",
            ),
            CONTEXT,
        )
        async with asyncio.timeout(60):
            await app.entrypoint().continue_run(run_id, CONTEXT, agent=restored)
            while (await app.runtime.get_run(run_id)).state.value in {
                "created",
                "queued",
                "running",
                "resuming",
                "accepted",
            }:
                await asyncio.sleep(0.01)
        assert (await app.runtime.get_run(run_id)).state.value == "completed"
        assert (tmp_path / "workspace/restored.txt").read_text() == "original"
        for role, request in models.seen:
            if role in {"director", "director.maker"}:
                assert "changed" not in request.model_dump_json()
                local = "maker" if role == "director.maker" else role
                assert request.model_binding == local
                assert "PRELOAD " + local in request.model_dump_json()
        envs = [environment(request) for _, request in models.seen]
        assert len({e["sandbox_id"] for e in envs}) == 1
        assert len({e["lease_owner_run_id"] for e in envs}) == 3
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_public_builder_nested_pause_cold_restart_keeps_frozen_revision(tmp_path):
    await pause_nested(tmp_path)
    await resume_nested(tmp_path)


def test_public_builder_nested_pause_recovers_in_a_new_python_process(tmp_path):
    for seed, phase in enumerate(("pause_nested", "resume_nested"), start=1):
        code = (
            "import asyncio, sys; from pathlib import Path; "
            f"from tests.sagents.v2.test_builder_nested_teams import {phase}; "
            f"asyncio.run({phase}(Path(sys.argv[1])))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            text=True,
            capture_output=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["private_child", "read_only_parent"])
async def test_nested_shared_members_inherit_actual_parent_policy(tmp_path, policy):
    models = Models(
        {
            "root": (delegate("director"),),
            "director": (delegate("maker"),),
            "director.maker": (
                ("file_write", {"file_path": "policy.txt", "content": "nested"}),
            ),
        }
    )
    app, bindings, _ = await open_app(tmp_path, models)
    try:
        root = await load_tree(app)
        result, _ = await run(
            app, root, config=RunConfig(metadata={"workspace_policy": policy})
        )
        assert result.state.value == "completed"
        envs = [environment(request) for _, request in models.seen]
        assert len({e["sandbox_id"] for e in envs}) == 1
        assert len({e["lease_owner_run_id"] for e in envs}) == 3
        row = next(iter(bindings.sandbox_provider._rows.values()))
        assert not (tmp_path / "workspace/policy.txt").exists()
        if policy == "private_child":
            assert (row.root / "policy.txt").read_text() == "nested"
            assert row.root != tmp_path / "workspace"
        else:
            request = next(r for role, r in models.seen if role == "director.maker")
            events = await app.runtime.session_store.read_events(request.run_id)
            assert any(e.type == "tool.call.failed" for e in events)
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_nested_local_alias_can_continue_its_durable_child_session(tmp_path):
    def followup(request):
        for message in reversed(request.messages):
            if message.role != "tool":
                continue
            for block in message.content:
                value = getattr(block, "value", None)
                if value is None:
                    try:
                        value = json.loads(getattr(block, "text", ""))
                    except ValueError:
                        continue
                if isinstance(value, dict) and "results" in value:
                    session = value["results"][0]["child_session_id"]
                    assert session
                    return "sys_team_delegate_task", {
                        "tasks": [
                            {
                                "agent_id": "maker",
                                "session_id": session,
                                "content": "follow up",
                            }
                        ]
                    }
        raise AssertionError("missing durable child result")

    models = Models(
        {
            "root": (delegate("director"),),
            "director": (delegate("maker"), followup),
            "director.maker": (
                ("file_write", {"file_path": "followup.txt", "content": "result"}),
            ),
        }
    )
    app, bindings, _ = await open_app(tmp_path, models)
    try:
        root = await load_tree(app)
        result, _ = await run(app, root)
        assert result.state.value == "completed"
        requests = [r for role, r in models.seen if role == "director.maker"]
        assert len({r.run_id for r in requests}) == 2
        commands = [
            await app.runtime.get_run(run_id) for run_id in {r.run_id for r in requests}
        ]
        assert len({command.session_id for command in commands}) == 1
        director = next(r for role, r in models.seen if role == "director")
        events = await app.runtime.session_store.read_events(director.run_id)
        assert not [e for e in events if e.type == "tool.call.failed"]
    finally:
        await app.close()
        await bindings.close()
