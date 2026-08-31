from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.contracts import (
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    SteerRun,
    StartRun,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    SessionCommitProposalStatus,
)
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.flow import FlowNodeResult, FlowRuntime
from sagents.v2.package.manifest.flows import FlowDefinition, FlowEdge, FlowNode
from sagents.v2.runtime.session.ephemeral import EphemeralSessionStore
from sagents.v2.runtime.session.filesystem import FilesystemSessionStore


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_1",
        principal_type=PrincipalType.USER,
        tenant_id="tenant_1",
    )
)


def command(key="start", *, session_id=None, mode=SessionConcurrencyMode.SERIAL):
    return StartRun(
        session_id=session_id,
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        session_concurrency_mode=mode,
        resolved_spec_hash="sha256:agent",
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_empty_database_capabilities_and_restart_round_trip(tmp_path):
    path = tmp_path / "runtime.db"
    first = FilesystemSessionStore(path)
    assert first.capabilities["durable_across_process_restart"] is True
    created = await first.create_run(command(), CONTEXT)
    await first.close()

    second = FilesystemSessionStore(path)
    run = await second.get_run(created.handle.run_id)
    session = await second.get_session(created.handle.session_id)
    events = await second.read_events(created.handle.run_id)
    duplicate = await second.create_run(command(), CONTEXT)

    assert run.state == RunState.QUEUED
    assert session.revision == 1
    assert [event.type for event in events] == [
        "run.accepted",
        "run.queued",
        "message.completed",
    ]
    assert duplicate.duplicate is True
    assert duplicate.handle.run_id == created.handle.run_id
    await second.close()


@pytest.mark.asyncio
async def test_concurrent_acknowledged_writes_survive_restart(tmp_path):
    path = tmp_path / "runtime.db"
    repository = FilesystemSessionStore(path)
    results = await asyncio.gather(
        *(
            repository.create_run(
                command(
                    f"start_{index}",
                    mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                ),
                CONTEXT,
            )
            for index in range(20)
        )
    )
    run_ids = {result.handle.run_id for result in results}
    await repository.close()

    restored = FilesystemSessionStore(path)
    restored_runs = await asyncio.gather(
        *(restored.get_run(run_id) for run_id in run_ids)
    )
    assert len(restored_runs) == 20
    assert all(run.state == RunState.QUEUED for run in restored_runs)
    await restored.close()


@pytest.mark.asyncio
async def test_failed_write_does_not_advance_the_durable_delta_baseline(tmp_path):
    path = tmp_path / "failed-write-baseline"
    store = FilesystemSessionStore(path)
    first = await store.create_run(command("first"), CONTEXT)
    original_write = store._write_session_state
    failed_once = False

    def fail_before_write(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise OSError("injected storage failure")
        return original_write(*args, **kwargs)

    store._write_session_state = fail_before_write
    with pytest.raises(OSError, match="injected storage failure"):
        await store.create_run(
            command(
                "uncertain",
                session_id=first.handle.session_id,
                mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            ),
            CONTEXT,
        )

    # The next write must compact from the current aggregate rather than append
    # a delta whose previous revision was never durably acknowledged.
    await store.create_run(
        command(
            "recovery",
            session_id=first.handle.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
        ),
        CONTEXT,
    )
    await store.close()

    reopened = FilesystemSessionStore(path)
    runs = await reopened.list_session_runs(first.handle.session_id)
    assert len(runs) == 3
    await reopened.close()


@pytest.mark.asyncio
async def test_create_transaction_recovers_missing_start_idempotency_lookup(tmp_path):
    path = tmp_path / "create-lookup-recovery"
    store = FilesystemSessionStore(path)
    original_lookup_write = store._write_start_idempotency

    def fail_lookup(*args, **kwargs):
        raise OSError("injected lookup failure")

    store._write_start_idempotency = fail_lookup
    with pytest.raises(OSError, match="injected lookup failure"):
        await store.create_run(command("create-once"), CONTEXT)
    store._write_start_idempotency = original_lookup_write
    await store.close()

    assert tuple((path / ".session-store/transactions").glob("*.json"))
    reopened = FilesystemSessionStore(path)
    duplicate = await reopened.create_run(command("create-once"), CONTEXT)
    assert duplicate.duplicate is True
    assert not tuple((path / ".session-store/transactions").glob("*.json"))
    await reopened.close()


@pytest.mark.asyncio
async def test_reopen_does_not_materialize_a_global_session_collection(tmp_path):
    path = tmp_path / "session-store"
    first = FilesystemSessionStore(path)
    one = await first.create_run(command("one"), CONTEXT)
    two = await first.create_run(command("two"), CONTEXT)
    await first.close()

    reopened = FilesystemSessionStore(path)
    assert reopened._loaded_session_ids == set()

    await reopened.get_session(one.handle.session_id)
    assert reopened._loaded_session_ids == {one.handle.session_id}
    assert two.handle.session_id not in reopened._sessions
    assert not hasattr(reopened, "list_sessions")
    await reopened.close()


@pytest.mark.asyncio
async def test_fork_sessions_are_nested_and_parent_delete_cascades(tmp_path):
    path = tmp_path / "session-store"
    store = FilesystemSessionStore(path)
    parent = await store.create_run(command("parent"), CONTEXT)
    await store.commit_run(
        run_id=parent.handle.run_id,
        expected_revision=parent.handle.run_revision,
        expected_states={RunState.QUEUED},
        new_state=RunState.CANCELLED,
        drafts=(),
        context=CONTEXT,
        idempotency_key="cancel-parent",
    )
    child = await store.create_run(
        command(
            "fork-child",
            session_id=parent.handle.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )
    grandchild = await store.create_run(
        command(
            "fork-grandchild",
            session_id=child.handle.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )

    for created, key in (
        (child, "cancel-child"),
        (grandchild, "cancel-grandchild"),
    ):
        await store.commit_run(
            run_id=created.handle.run_id,
            expected_revision=created.handle.run_revision,
            expected_states={RunState.QUEUED},
            new_state=RunState.CANCELLED,
            drafts=(),
            context=CONTEXT,
            idempotency_key=key,
        )

    parent_dir = path / "sessions" / parent.handle.session_id
    child_dir = parent_dir / "sub_sessions" / child.handle.session_id
    grandchild_dir = child_dir / "sub_sessions" / grandchild.handle.session_id
    child_manifest = json.loads(
        (child_dir / "session.json").read_text(encoding="utf-8")
    )
    assert child_dir.parent == parent_dir / "sub_sessions"
    assert grandchild_dir.parent == child_dir / "sub_sessions"
    assert not (path / "sessions" / child.handle.session_id).exists()
    assert not (path / "sessions" / grandchild.handle.session_id).exists()
    assert child_manifest["session"]["parent_session_id"] == parent.handle.session_id
    assert (
        child_dir / "runs" / child.handle.run_id / "fork-base-events.jsonl"
    ).is_file()

    await store.close()

    # Normalize the short-lived early-v2 sibling layout without consulting v1.
    sibling_child_dir = path / "sessions" / child.handle.session_id
    shutil.move(child_dir, sibling_child_dir)
    shutil.rmtree(path / ".session-store" / "locations")
    (path / ".session-store" / "locations").mkdir()

    store = FilesystemSessionStore(path)
    assert child_dir.is_dir()
    assert grandchild_dir.is_dir()
    assert not sibling_child_dir.exists()
    descendants = await store.list_descendant_sessions(parent.handle.session_id)
    assert [value.session_id for value in descendants] == [
        child.handle.session_id,
        grandchild.handle.session_id,
    ]
    assert (await store.get_session(child.handle.session_id)).parent_session_id == (
        parent.handle.session_id
    )
    assert await store.read_fork_base_events(child.handle.run_id)

    await store.delete_session(parent.handle.session_id)
    assert not parent_dir.exists()
    assert not child_dir.exists()
    assert not grandchild_dir.exists()
    await store.close()

    reopened = FilesystemSessionStore(path)
    for deleted_session_id in (
        parent.handle.session_id,
        child.handle.session_id,
        grandchild.handle.session_id,
    ):
        with pytest.raises(SageV2Error) as missing:
            await reopened.get_session(deleted_session_id)
        assert missing.value.info.code == "session.not_found"
    await reopened.close()


@pytest.mark.asyncio
async def test_runtime_session_tree_stream_keeps_parent_and_child_cursors(tmp_path):
    store = FilesystemSessionStore(tmp_path / "session-tree-stream")
    runtime = HarnessRuntime(store)
    parent = await runtime.start_run(command("tree-parent"), CONTEXT)
    child = await runtime.start_run(
        command(
            "tree-child",
            session_id=parent.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )

    stream = runtime.subscribe_session_tree(parent.session_id)
    discovered: set[str] = set()
    event_runs: set[str] = set()
    while discovered != {parent.session_id, child.session_id} or event_runs != {
        parent.run_id,
        child.run_id,
    }:
        observation = await asyncio.wait_for(anext(stream), timeout=1)
        if observation.kind == "session.discovered":
            discovered.add(observation.session.session_id)
        elif observation.event is not None:
            event_runs.add(observation.event.run_id)

    assert discovered == {parent.session_id, child.session_id}
    assert event_runs == {parent.run_id, child.run_id}
    await stream.aclose()
    await store.close()


@pytest.mark.asyncio
async def test_descendants_only_tree_stream_waits_for_late_child(tmp_path):
    store = FilesystemSessionStore(tmp_path / "late-child-session-tree-stream")
    runtime = HarnessRuntime(store)
    parent = await runtime.start_run(command("late-tree-parent"), CONTEXT)

    stream = runtime.subscribe_session_tree(
        parent.session_id,
        include_root=False,
    )
    first_observation = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.05)
    assert not first_observation.done()

    child = await runtime.start_run(
        command(
            "late-tree-child",
            session_id=parent.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )

    discovered = await asyncio.wait_for(first_observation, timeout=1)
    assert discovered.kind == "session.discovered"
    assert discovered.session.session_id == child.session_id
    assert discovered.session.parent_session_id == parent.session_id

    while True:
        child_event = await asyncio.wait_for(anext(stream), timeout=1)
        if (
            child_event.event is not None
            and child_event.event.type == "message.completed"
        ):
            break
    assert child_event.kind == "session.event"
    assert child_event.event is not None
    assert child_event.event.session_id == child.session_id
    await stream.aclose()
    await store.close()


@pytest.mark.asyncio
async def test_export_import_rejects_corrupt_run_sequence_without_mutation():
    source = EphemeralSessionStore()
    created = await source.create_run(command(), CONTEXT)
    payload = await source.export_state()
    payload["runs"][0]["last_run_sequence"] = 99

    target = EphemeralSessionStore()
    with pytest.raises(SageV2Error) as corrupt:
        await target.load_state(payload)
    assert corrupt.value.info.code == "session_store.corrupt_sequence"
    with pytest.raises(SageV2Error) as missing:
        await target.get_run(created.handle.run_id)
    assert missing.value.info.code == "run.not_found"


def test_snapshot_checksum_corruption_is_detected_on_open(tmp_path):
    path = tmp_path / "session-store"

    async def create():
        repository = FilesystemSessionStore(path)
        created = await repository.create_run(command(), CONTEXT)
        await repository.close()
        return created

    created = asyncio.run(create())
    snapshot = next((path / "sessions").glob("*/state.json"))
    envelope = json.loads(snapshot.read_text(encoding="utf-8"))
    envelope["checksum"] = "sha256:tampered"
    snapshot.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")

    reopened = FilesystemSessionStore(path)
    with pytest.raises(SageV2Error) as mismatch:
        asyncio.run(reopened.get_session(created.handle.session_id))
    assert mismatch.value.info.code == "session_store.hash_mismatch"
    asyncio.run(reopened.close())


def test_interrupted_temporary_snapshot_is_ignored(tmp_path):
    path = tmp_path / "session-store"

    async def create():
        store = FilesystemSessionStore(path)
        created = await store.create_run(command(), CONTEXT)
        await store.close()
        return created

    created = asyncio.run(create())
    snapshot = next((path / "sessions").glob("*/state.json"))
    snapshot.with_name(".state.json.interrupted").write_bytes(
        b'{"format":"interrupted"'
    )

    restored = FilesystemSessionStore(path)
    run = asyncio.run(restored.get_run(created.handle.run_id))
    asyncio.run(restored.close())
    assert run.state == RunState.QUEUED


@pytest.mark.asyncio
async def test_session_journal_appends_deltas_without_full_state_amplification(
    tmp_path,
):
    path = tmp_path / "session-store"
    store = FilesystemSessionStore(path)
    created = await store.create_run(command("bounded"), CONTEXT)
    for index in range(30):
        await store.create_run(
            command(
                f"bounded-{index}",
                session_id=created.handle.session_id,
                mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            ),
            CONTEXT,
        )
    exported = store._dump_session_state_locked(created.handle.session_id)
    await store.close()

    session_dir = path / "sessions" / created.handle.session_id
    snapshot = session_dir / "state.json"
    journal = session_dir / "journal.jsonl"
    assert snapshot.is_file()
    assert journal.is_file()
    assert len(list(session_dir.glob("state*.json"))) == 1
    current_state_size = len(
        json.dumps(exported, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert snapshot.stat().st_size + journal.stat().st_size < current_state_size * 3

    restored = FilesystemSessionStore(path)
    assert len(await restored.list_session_runs(created.handle.session_id)) == 31
    await restored.close()


def test_truncated_v3_journal_tail_is_ignored_but_middle_checksum_is_not(tmp_path):
    path = tmp_path / "session-store"

    async def create():
        store = FilesystemSessionStore(path)
        first = await store.create_run(command("journal-base"), CONTEXT)
        await store.create_run(
            command(
                "journal-next",
                session_id=first.handle.session_id,
                mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            ),
            CONTEXT,
        )
        await store.close()
        return first

    first = asyncio.run(create())
    journal = path / "sessions" / first.handle.session_id / "journal.jsonl"
    original = journal.read_bytes()
    journal.write_bytes(original + b'{"format":"incomplete"')
    restored = FilesystemSessionStore(path)
    assert len(asyncio.run(restored.list_session_runs(first.handle.session_id))) == 2
    asyncio.run(restored.close())

    journal.write_bytes(
        original.replace(b'"checksum":"sha256:', b'"checksum":"sha256:0', 1)
    )
    corrupted = FilesystemSessionStore(path)
    with pytest.raises(SageV2Error) as mismatch:
        asyncio.run(corrupted.get_session(first.handle.session_id))
    assert mismatch.value.info.code == "session_store.hash_mismatch"
    asyncio.run(corrupted.close())


@pytest.mark.asyncio
async def test_readable_session_views_are_repaired_from_authoritative_state(tmp_path):
    path = tmp_path / "session-store"
    first = FilesystemSessionStore(path)
    created = await first.create_run(command("repair-views"), CONTEXT)
    await first.close()

    session_dir = path / "sessions" / created.handle.session_id
    (session_dir / "session.json").unlink()
    shutil.rmtree(session_dir / "runs")

    reopened = FilesystemSessionStore(path)
    await reopened.get_session(created.handle.session_id)
    await reopened.close()

    assert (session_dir / "session.json").is_file()
    assert (session_dir / "runs" / created.handle.run_id / "events.jsonl").is_file()


WRITE_TOOL = ToolDefinition(
    name="write_value",
    description="write",
    input_schema={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    },
    side_effect_level=SideEffectLevel.WRITE,
)


def completed(text="", calls=()):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1",
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
        ),
    )


@pytest.mark.asyncio
async def test_snapshot_publication_and_idempotency_survive_filesystem_restart(
    tmp_path,
):
    path = tmp_path / "runtime.db"
    repository = FilesystemSessionStore(path)
    runtime = HarnessRuntime(repository)
    handle = await runtime.start_run(
        command("snapshot", mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED), CONTEXT
    )
    completed_run = await AgentLoopEngine(
        runtime=runtime,
        model=ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("candidate"),)),)
        ),
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
    ).execute(handle.run_id, CONTEXT)
    propose_command = ProposeSessionCommit(
        run_id=handle.run_id,
        expected_run_revision=completed_run.revision,
        idempotency_key="propose",
    )
    proposal = await runtime.propose_session_commit(propose_command, CONTEXT)
    assert await runtime.propose_session_commit(propose_command, CONTEXT) == proposal
    session = await repository.get_session(handle.session_id)
    publish_command = PublishSessionCommit(
        proposal_id=proposal.proposal_id,
        expected_proposal_revision=proposal.revision,
        expected_session_revision=session.revision,
        idempotency_key="publish",
    )
    published = await runtime.publish_session_commit(publish_command, CONTEXT)
    assert published.status == SessionCommitProposalStatus.PUBLISHED
    await repository.close()

    reopened = FilesystemSessionStore(path)
    restored = await reopened.get_session_commit_proposal(proposal.proposal_id)
    duplicate = await reopened.publish_session_commit(publish_command, CONTEXT)
    assert restored == published
    assert duplicate == published
    assert reopened.capabilities["supports_snapshot_publication"] is True
    await reopened.close()


async def handler(call, context):
    return ToolExecutionResult(
        tool_call_id=call.tool_call_id,
        operation_id=call.operation_id,
        content=(TextBlock(text="written"),),
    )


def loop_for(runtime, model, executor):
    return AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((WRITE_TOOL,)),
        tool_executor=executor,
    )


@pytest.mark.asyncio
async def test_suspended_approval_resumes_after_store_process_reopen(tmp_path):
    path = tmp_path / "runtime.db"
    repository = FilesystemSessionStore(path)
    runtime = HarnessRuntime(repository)
    handle = await runtime.start_run(command(), CONTEXT)
    first_model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_1",
                                name="write_value",
                                arguments={"value": "1"},
                            ),
                        )
                    ),
                )
            ),
        )
    )
    first_executor = InMemoryToolExecutor(
        {"write_value": WRITE_TOOL}, {"write_value": handler}
    )
    suspended = await loop_for(runtime, first_model, first_executor).execute(
        handle.run_id, CONTEXT
    )
    assert suspended.state == RunState.SUSPENDED
    assert first_executor.calls == []
    await repository.close()

    restored_repository = FilesystemSessionStore(path)
    restored_runtime = HarnessRuntime(restored_repository)
    restored_run = await restored_runtime.get_run(handle.run_id)
    suspension = await restored_repository.get_suspension(restored_run.suspension_id)
    interaction = await restored_repository.get_interaction(suspension.interaction_id)
    checkpoint = await restored_repository.get_checkpoint(suspension.checkpoint_id)
    assert checkpoint.checkpoint_codec_version == "agent-loop/3"
    assert "messages" not in checkpoint.state
    assert checkpoint.state["ledger_digest"].startswith("sha256:")
    receipt = await restored_runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=restored_run.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once",
            idempotency_key="approve",
        ),
        CONTEXT,
    )
    assert receipt.decision.value == "accepted"
    second_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("done"),)),)
    )
    second_executor = InMemoryToolExecutor(
        {"write_value": WRITE_TOOL}, {"write_value": handler}
    )
    completed_run = await loop_for(
        restored_runtime, second_model, second_executor
    ).resume(handle.run_id, CONTEXT)

    assert completed_run.state == RunState.COMPLETED
    assert len(second_executor.calls) == 1
    events = await restored_repository.read_events(handle.run_id)
    assert [event.run_sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.type for event in events].count("tool.call.succeeded") == 1
    await restored_repository.close()


@pytest.mark.asyncio
async def test_steer_inbox_and_claim_cursor_survive_filesystem_restarts(tmp_path):
    path = tmp_path / "runtime.db"
    repository = FilesystemSessionStore(path)
    runtime = HarnessRuntime(repository)
    handle = await runtime.start_run(command(), CONTEXT)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=CONTEXT,
        idempotency_key="start_execution",
    )
    receipt = await runtime.steer_run(
        SteerRun(
            run_id=handle.run_id,
            expected_revision=running.revision,
            expected_turn_id="turn_1",
            input=(InputItem(role="user", content=(TextBlock(text="new input"),)),),
            idempotency_key="steer_1",
        ),
        CONTEXT,
    )
    assert receipt.decision.value == "accepted"
    await repository.close()

    restored = FilesystemSessionStore(path)
    current = await restored.get_run(handle.run_id)
    claimed = await restored.claim_steers(
        run_id=handle.run_id,
        expected_revision=current.revision,
        turn_id="turn_1",
        context=CONTEXT,
    )
    assert [entry.input[0].content[0].text for entry in claimed.entries] == [
        "new input"
    ]
    await restored.close()

    reopened = FilesystemSessionStore(path)
    current = await reopened.get_run(handle.run_id)
    claimed_again = await reopened.claim_steers(
        run_id=handle.run_id,
        expected_revision=current.revision,
        turn_id="turn_1",
        context=CONTEXT,
    )
    assert claimed_again.entries == ()
    await reopened.close()


@pytest.mark.asyncio
async def test_nested_flow_interaction_stack_survives_filesystem_restart(tmp_path):
    path = tmp_path / "runtime.db"
    flows = {
        "main": FlowDefinition(
            version="1",
            start="delegate",
            nodes=(FlowNode(id="delegate", type="subflow", flow="child"),),
            edges=(FlowEdge(**{"from": "delegate", "to": "end"}),),
        ),
        "child": FlowDefinition(
            version="1",
            start="approval",
            nodes=(
                FlowNode(
                    id="approval",
                    type="interaction",
                    interaction="approval",
                    blocking_scope="run",
                ),
                FlowNode(id="work", type="agent", agent="worker"),
            ),
            edges=(
                FlowEdge(**{"from": "approval", "to": "work", "when": "approved"}),
                FlowEdge(**{"from": "approval", "to": "end", "when": "denied"}),
                FlowEdge(**{"from": "work", "to": "end"}),
            ),
        ),
    }

    class Worker:
        def __init__(self):
            self.calls = 0

        async def run(self, context):
            self.calls += 1
            return FlowNodeResult(output={"restored": True})

    first_repository = FilesystemSessionStore(path)
    first_runtime = HarnessRuntime(first_repository)
    handle = await first_runtime.start_run(command(), CONTEXT)
    suspended = await FlowRuntime(
        runtime=first_runtime,
        flows=flows,
        agent_nodes={"worker": Worker()},
    ).execute(handle.run_id, "main", CONTEXT)
    assert suspended.state == RunState.SUSPENDED
    checkpoint = await first_repository.get_latest_checkpoint(handle.run_id)
    assert checkpoint.state["subflow_stack"][0]["flow_id"] == "child"
    await first_repository.close()

    restored_repository = FilesystemSessionStore(path)
    restored_runtime = HarnessRuntime(restored_repository)
    restored_run = await restored_runtime.get_run(handle.run_id)
    suspension = await restored_repository.get_suspension(restored_run.suspension_id)
    interaction = await restored_repository.get_interaction(suspension.interaction_id)
    await restored_runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=restored_run.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve",
            idempotency_key="approve_nested_flow",
        ),
        CONTEXT,
    )
    worker = Worker()
    completed_run = await FlowRuntime(
        runtime=restored_runtime,
        flows=flows,
        agent_nodes={"worker": worker},
    ).resume(handle.run_id, CONTEXT)

    assert completed_run.state == RunState.COMPLETED
    assert worker.calls == 1
    events = await restored_repository.read_events(handle.run_id)
    assert [event.run_sequence for event in events] == list(range(1, len(events) + 1))
    await restored_repository.close()
