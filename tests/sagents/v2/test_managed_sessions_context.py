"""Leaders recover delegated conversation identities without tool receipts."""

import json

import pytest

from sagents.v2.agent.multi_agent import AgentDescriptor, AgentMode, AgentRegistry
from sagents.v2.agent.multi_agent.context import AgentRosterContextProvider
from sagents.v2.agent.modes.loop_factory import ModeAwareAgentLoopFactory
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.contracts.commands import CancelRun, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from tests.sagents.v2.test_session_history_context_matrix import (
    CONTEXT,
    command,
    completed,
)


def rows(segments):
    content = next(s.content for s in segments if s.segment_id == "managed_sessions")
    return json.loads(content.splitlines()[-2])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [AgentMode.TEAM, AgentMode.FIBRE])
async def test_created_children_survive_cancellation_restart_and_followup(
    tmp_path, mode
):
    path = tmp_path / "store"
    store = FilesystemSessionStore(path)
    runtime = HarnessRuntime(store)
    parent_command = command("work", "parent")
    parent = await runtime.start_run(parent_command, CONTEXT)
    long_name = "检查登录页面深色模式与浅色模式下的所有交互细节以及错误信息"

    async def child(
        key, *, parent_run_id=parent.run_id, invocation="delegation", session_id=None
    ):
        return await runtime.start_run(
            StartRun(
                agent_id="qualified.reviewer",
                parent_run_id=parent_run_id,
                session_id=session_id,
                input=(),
                invocation_mode=invocation,
                resolved_spec_hash="sha256:child",
                idempotency_key=key,
                config={
                    "metadata": {
                        "task_name": long_name + "\nextra",
                        "original_task": "PRIVATE FULL TASK",
                    }
                },
            ),
            CONTEXT,
        )

    first = await child("first")
    second = await child("second")
    nested = await child("nested", parent_run_id=first.run_id)
    unrelated = await runtime.start_run(command("other", "other-parent"), CONTEXT)
    other = await child("other", parent_run_id=unrelated.run_id)
    flow = await child("flow", invocation="flow")
    # No child execution and no delegation result exists in the leader history.
    await runtime.cancel_run(
        CancelRun(
            run_id=first.run_id,
            expected_revision=0,
            idempotency_key="cancel-first",
        ),
        CONTEXT,
    )
    await runtime.cancel_run(
        CancelRun(
            run_id=parent.run_id, expected_revision=0, idempotency_key="cancel-parent"
        ),
        CONTEXT,
    )
    await store.close()

    store = FilesystemSessionStore(path)
    runtime = HarnessRuntime(store)
    registry = AgentRegistry(
        (
            AgentDescriptor(
                agent_id="qualified.reviewer",
                name="Reviewer",
                description="Review",
                instructions="Review",
            ),
        ),
        aliases={"reviewer": "qualified.reviewer"},
    )
    provider = AgentRosterContextProvider(registry, mode, session_store=store)
    try:
        # The next leader Run must recover children from the previous Run.
        parent_command = command(
            "continue", "next-parent", session_id=parent.session_id
        )
        parent = await runtime.start_run(parent_command, CONTEXT)
        segments = await provider.segments(parent_command, run_id=parent.run_id)
        entries = rows(segments)
        assert {r["session_id"] for r in entries} == {
            first.session_id,
            second.session_id,
        }
        assert {r["agent_id"] for r in entries} == {"reviewer"}
        assert {r["task"] for r in entries} == {long_name[:20]}
        assert {r["state"] for r in entries} == {"cancelled", "queued"}
        text = str(segments)
        assert "PRIVATE FULL TASK" not in text
        assert all(h.session_id not in text for h in (nested, other, flow))

        follow = await runtime.start_run(
            StartRun(
                agent_id="qualified.reviewer",
                parent_run_id=parent.run_id,
                session_id=first.session_id,
                input=(),
                invocation_mode="delegation",
                resolved_spec_hash="sha256:child",
                idempotency_key="follow",
                config={"metadata": {"task_name": "repair\n  now"}},
            ),
            CONTEXT,
        )
        updated = rows(await provider.segments(parent_command, run_id=parent.run_id))
        assert len(updated) == 2
        assert next(r for r in updated if r["session_id"] == follow.session_id) == {
            "agent_id": "reviewer",
            "session_id": first.session_id,
            "state": "queued",
            "task": "repair now",
        }
        # Even with runtime_context_in_user enabled, the index stays in system.
        messages = await DefaultContextAssembler(
            providers=(provider,)
        ).prepare_messages(
            parent_command,
            (),
            run_id=parent.run_id,
        )
        assert any(
            m.role == "system"
            and any(
                isinstance(b, TextBlock) and "<managed_sessions>" in b.text
                for b in m.content
            )
            for m in messages
        )
        leaf = AgentRosterContextProvider(
            registry, mode, allow_delegation=False, session_store=store
        )
        assert [
            s.segment_id
            for s in await leaf.segments(parent_command, run_id=parent.run_id)
        ] == ["agent_delegation_boundary"]
        model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
        factory = ModeAwareAgentLoopFactory(
            runtime=runtime,
            registry=registry,
            model_factory=lambda *_: model,
            base_catalog=InMemoryToolCatalog(()),
            base_executor=InMemoryToolExecutor({}, {}),
            resolved_spec_hash="sha256:agent",
        )
        loop = factory.create_loop(
            AgentDescriptor(
                agent_id="agent_1",
                name="Leader",
                description="Lead",
                instructions="Lead",
                mode=mode,
            ),
            parent.run_id,
        )
        result = await loop.execute(parent.run_id, CONTEXT)
        assert result.state.value == "completed"
        system = "\n".join(
            b.text
            for m in model.requests[0].messages
            if m.role == "system"
            for b in m.content
            if isinstance(b, TextBlock)
        )
        assert first.session_id in system and second.session_id in system
        assert "<managed_sessions>" in system
    finally:
        await store.close()
