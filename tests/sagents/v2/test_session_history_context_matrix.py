from __future__ import annotations

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.runtime.session import FilesystemSessionStore


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


def command(
    text: str,
    key: str,
    *,
    session_id: str | None = None,
    mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL,
    base_revision: int | None = None,
) -> StartRun:
    return StartRun(
        session_id=session_id,
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text=text),)),),
        session_concurrency_mode=mode,
        base_session_revision=base_revision,
        resolved_spec_hash="sha256:agent",
        idempotency_key=key,
    )


def completed(
    text: str = "",
    *,
    calls: tuple[ModelToolCall, ...] = (),
    provider_state: dict | None = None,
):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1",
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            provider_state=provider_state or {},
        ),
    )


def message_texts(request) -> list[tuple[str, str]]:
    return [
        (
            message.role,
            "\n".join(
                block.text for block in message.content if isinstance(block, TextBlock)
            ),
        )
        for message in request.messages
    ]


async def execute(runtime, handle, model, *, definitions=(), handlers=None):
    definitions = tuple(definitions)
    catalog = InMemoryToolCatalog(definitions)
    executor = InMemoryToolExecutor(
        {value.name: value for value in definitions}, handlers or {}
    )
    return await AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=catalog,
        tool_executor=executor,
    ).execute(handle.run_id, CONTEXT)


@pytest.mark.asyncio
async def test_serial_run_projects_completed_history_from_previous_runs():
    runtime = ephemeral_runtime()
    first = await runtime.start_run(command("first question", "first"), CONTEXT)
    await execute(
        runtime,
        first,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("first answer"),)),)
        ),
    )

    second = await runtime.start_run(
        command("follow up", "second", session_id=first.session_id), CONTEXT
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("second answer"),)),)
    )
    await execute(runtime, second, model)

    assert message_texts(model.requests[0]) == [
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "follow up"),
    ]


@pytest.mark.asyncio
async def test_provider_state_survives_tool_round_trip_and_session_rebuild():
    runtime = ephemeral_runtime()
    call = ModelToolCall(
        tool_call_id="call_reasoning",
        name="lookup",
        arguments={"q": "state"},
    )
    state = {
        "openai_compatible": {
            "reasoning_details": [{"type": "reasoning", "value": "opaque"}]
        }
    }
    definition = ToolDefinition(
        name="lookup",
        description="lookup",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )
    first = await runtime.start_run(command("first", "state-first"), CONTEXT)
    first_model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed(calls=(call,), provider_state=state),)
            ),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )

    async def lookup(tool_call, _context):
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="result"),),
            metadata={
                "context_reference": {
                    "uri": "artifact://tool-result/call_reasoning"
                }
            },
        )

    await execute(
        runtime,
        first,
        first_model,
        definitions=(definition,),
        handlers={"lookup": lookup},
    )

    assert first_model.requests[1].messages[-2].provider_state == state
    assert first_model.requests[1].messages[-1].metadata[
        "context_reference"
    ]["uri"] == "artifact://tool-result/call_reasoning"
    second = await runtime.start_run(
        command("follow up", "state-second", session_id=first.session_id),
        CONTEXT,
    )
    second_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("again"),)),)
    )
    await execute(runtime, second, second_model)
    replayed = next(
        message
        for message in second_model.requests[0].messages
        if message.tool_calls
        and message.tool_calls[0].tool_call_id == "call_reasoning"
    )
    assert replayed.provider_state == state
    replayed_tool = next(
        message
        for message in second_model.requests[0].messages
        if message.role == "tool" and message.tool_call_id == "call_reasoning"
    )
    assert replayed_tool.metadata["context_reference"]["uri"] == (
        "artifact://tool-result/call_reasoning"
    )


@pytest.mark.asyncio
async def test_fork_materializes_parent_history_at_its_stable_base_sequence():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(command("parent question", "parent"), CONTEXT)
    await execute(
        runtime,
        parent,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("parent answer"),)),)
        ),
    )
    parent_snapshot = await runtime.session_store.get_session(parent.session_id)

    child = await runtime.start_run(
        command(
            "delegated question",
            "child",
            session_id=parent.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("child answer"),)),)
    )
    await execute(runtime, child, model)

    assert child.session_id != parent.session_id
    assert child.base_session_sequence == parent_snapshot.last_sequence
    assert message_texts(model.requests[0]) == [
        ("user", "parent question"),
        ("assistant", "parent answer"),
        ("user", "delegated question"),
    ]


@pytest.mark.asyncio
async def test_snapshot_reads_its_base_but_is_not_published_into_serial_history():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("seed question", "seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("seed answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)

    snapshot = await runtime.start_run(
        command(
            "private candidate",
            "snapshot",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )
    snapshot_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("private answer"),)),)
    )
    await execute(runtime, snapshot, snapshot_model)

    serial = await runtime.start_run(
        command("public follow up", "serial", session_id=seed.session_id), CONTEXT
    )
    serial_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("public answer"),)),)
    )
    await execute(runtime, serial, serial_model)

    assert message_texts(snapshot_model.requests[0]) == [
        ("user", "seed question"),
        ("assistant", "seed answer"),
        ("user", "private candidate"),
    ]
    assert message_texts(serial_model.requests[0]) == [
        ("user", "seed question"),
        ("assistant", "seed answer"),
        ("user", "public follow up"),
    ]


@pytest.mark.asyncio
async def test_snapshot_publication_is_explicit_and_visible_only_after_publish_boundary():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("seed", "publish-seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("seed answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)
    snapshot = await runtime.start_run(
        command(
            "candidate",
            "publish-snapshot",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )
    snapshot_run = await execute(
        runtime,
        snapshot,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("candidate answer"),)),)
        ),
    )
    proposal = await runtime.propose_session_commit(
        ProposeSessionCommit(
            run_id=snapshot.run_id,
            expected_run_revision=snapshot_run.revision,
            idempotency_key="propose",
        ),
        CONTEXT,
    )
    assert proposal.status == SessionCommitProposalStatus.PENDING
    assert proposal.conflicting_run_ids == ()

    # This Run fixes its history boundary before publication. Publishing later
    # must not retroactively change the ledger it executes from.
    accepted_before_publish = await runtime.start_run(
        command("already accepted", "before-publish", session_id=seed.session_id),
        CONTEXT,
    )
    session = await runtime.session_store.get_session(seed.session_id)
    published = await runtime.publish_session_commit(
        PublishSessionCommit(
            proposal_id=proposal.proposal_id,
            expected_proposal_revision=proposal.revision,
            expected_session_revision=session.revision,
            merge_strategy=SessionMergeStrategy.APPEND_AFTER_CURRENT,
            idempotency_key="publish",
        ),
        CONTEXT,
    )
    assert published.status == SessionCommitProposalStatus.PUBLISHED
    assert published.published_session_sequence is not None

    before_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("before answer"),)),)
    )
    await execute(runtime, accepted_before_publish, before_model)
    assert message_texts(before_model.requests[0]) == [
        ("user", "seed"),
        ("assistant", "seed answer"),
        ("user", "already accepted"),
    ]

    accepted_after_publish = await runtime.start_run(
        command("after publish", "after-publish", session_id=seed.session_id),
        CONTEXT,
    )
    after_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("after answer"),)),)
    )
    await execute(runtime, accepted_after_publish, after_model)
    assert message_texts(after_model.requests[0]) == [
        ("user", "seed"),
        ("assistant", "seed answer"),
        ("user", "candidate"),
        ("assistant", "candidate answer"),
        ("user", "already accepted"),
        ("assistant", "before answer"),
        ("user", "after publish"),
    ]


@pytest.mark.asyncio
async def test_snapshot_conflict_requires_explicit_append_or_can_be_rejected():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("seed", "conflict-seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("seed answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)
    snapshot = await runtime.start_run(
        command(
            "candidate",
            "conflict-snapshot",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )
    snapshot_run = await execute(
        runtime,
        snapshot,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("candidate answer"),)),)
        ),
    )
    concurrent = await runtime.start_run(
        command("canonical change", "conflict-serial", session_id=seed.session_id),
        CONTEXT,
    )
    await execute(
        runtime,
        concurrent,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("canonical answer"),)),)
        ),
    )
    proposal = await runtime.propose_session_commit(
        ProposeSessionCommit(
            run_id=snapshot.run_id,
            expected_run_revision=snapshot_run.revision,
            idempotency_key="conflict-propose",
        ),
        CONTEXT,
    )
    assert proposal.conflicting_run_ids == (concurrent.run_id,)
    session = await runtime.session_store.get_session(seed.session_id)
    with pytest.raises(SageV2Error) as conflict:
        await runtime.publish_session_commit(
            PublishSessionCommit(
                proposal_id=proposal.proposal_id,
                expected_proposal_revision=proposal.revision,
                expected_session_revision=session.revision,
                idempotency_key="require-clean-base",
            ),
            CONTEXT,
        )
    assert conflict.value.info.code == "session.commit_merge_required"

    rejected = await runtime.reject_session_commit(
        RejectSessionCommit(
            proposal_id=proposal.proposal_id,
            expected_proposal_revision=proposal.revision,
            expected_session_revision=session.revision,
            idempotency_key="reject-conflict",
            reason="candidate is obsolete",
        ),
        CONTEXT,
    )
    assert rejected.status == SessionCommitProposalStatus.REJECTED
    assert rejected.rejection_reason == "candidate is obsolete"


@pytest.mark.asyncio
async def test_stale_snapshot_never_reads_events_committed_after_its_base():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("base question", "stale-seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("base answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)
    snapshot = await runtime.start_run(
        command(
            "candidate question",
            "stale-candidate",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )

    later = await runtime.start_run(
        command("later question", "later", session_id=seed.session_id), CONTEXT
    )
    await execute(
        runtime,
        later,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("later answer"),)),)
        ),
    )
    snapshot_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("candidate answer"),)),)
    )
    await execute(runtime, snapshot, snapshot_model)

    assert snapshot.base_session_sequence == base.last_sequence
    assert message_texts(snapshot_model.requests[0]) == [
        ("user", "base question"),
        ("assistant", "base answer"),
        ("user", "candidate question"),
    ]


@pytest.mark.asyncio
async def test_sqlite_restart_preserves_the_session_history_anchor(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    repository = FilesystemSessionStore(path)
    runtime = HarnessRuntime(repository)
    first = await runtime.start_run(command("before restart", "restart-first"), CONTEXT)
    await execute(
        runtime,
        first,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("persisted answer"),)),)
        ),
    )
    await repository.close()

    reopened = FilesystemSessionStore(path)
    resumed_runtime = HarnessRuntime(reopened)
    second = await resumed_runtime.start_run(
        command("after restart", "restart-second", session_id=first.session_id), CONTEXT
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("new answer"),)),)
    )
    await execute(resumed_runtime, second, model)

    assert message_texts(model.requests[0]) == [
        ("user", "before restart"),
        ("assistant", "persisted answer"),
        ("user", "after restart"),
    ]
    await reopened.close()


@pytest.mark.asyncio
async def test_tool_call_and_result_items_reconstruct_a_complete_provider_pair():
    runtime = ephemeral_runtime()
    definition = ToolDefinition(
        name="lookup",
        description="look up a value",
        input_schema={"type": "object", "properties": {}},
        side_effect_level=SideEffectLevel.READ,
    )

    async def lookup(call, context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="tool value"),),
        )

    first = await runtime.start_run(command("use the tool", "tool-first"), CONTEXT)
    call = ModelToolCall(tool_call_id="call_1", name="lookup", arguments={})
    await execute(
        runtime,
        first,
        ScriptedModelProvider(
            (
                ScriptedModelStep(events=(completed(calls=(call,)),)),
                ScriptedModelStep(events=(completed("final answer"),)),
            )
        ),
        definitions=(definition,),
        handlers={"lookup": lookup},
    )

    second = await runtime.start_run(
        command("continue", "tool-second", session_id=first.session_id), CONTEXT
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("continued"),)),)
    )
    await execute(runtime, second, model)

    messages = model.requests[0].messages
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert messages[1].tool_calls == (call,)
    assert messages[2].tool_call_id == "call_1"
    assert messages[2].content == (TextBlock(text="tool value"),)
