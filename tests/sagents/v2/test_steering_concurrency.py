"""Turn-bound steering must not contend with execution CAS or lose its outcome."""
from __future__ import annotations

import asyncio
from typing import cast

import pytest
import pytest_asyncio

from sagents.v2.contracts.checkpoint import Checkpoint
from sagents.v2.contracts.commands import CommandDecision, InputItem, StartRun, SteerRun
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.events import CheckpointEventData, TurnEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.runtime.session.contracts import EventDraft, SessionStore
from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore

CONTEXT = RequestContext(actor=ActorRef(principal_id="owner", principal_type=PrincipalType.USER))


@pytest_asyncio.fixture(params=["ephemeral", "filesystem"])
async def running(request, tmp_path):
    store = (EphemeralSessionStore() if request.param == "ephemeral"
             else FilesystemSessionStore(tmp_path / "runtime.db"))
    runtime = HarnessRuntime(cast(SessionStore, store))
    handle = await runtime.start_run(StartRun(
        agent_id="agent", resolved_spec_hash="sha256:spec", idempotency_key="start",
        input=(InputItem(role="user", content=(TextBlock(text="start"),)),),
    ), CONTEXT)
    run = await runtime.start_execution(run_id=handle.run_id, expected_revision=0,
                                        context=CONTEXT, idempotency_key="execute")
    yield runtime, store, run
    await store.close()


async def progress(store, run, *, kind="turn.started", turn="turn_1", state=RunState.RUNNING):
    drafts = () if kind is None else (EventDraft(
        type=kind, turn_id=turn,
        data=TurnEventData(state="started" if kind == "turn.started" else "completed"),
    ),)
    return (await store.commit_run(
        run_id=run.run_id, expected_revision=run.revision,
        expected_states={run.state}, new_state=state, drafts=drafts,
        context=CONTEXT, idempotency_key=f"{kind}:{turn}:{run.revision}:{state}",
    )).run


def steer(run, key="steer", **updates):
    return SteerRun(
        run_id=run.run_id, expected_turn_id="turn_1", idempotency_key=key,
        input=(InputItem(role="user", content=(TextBlock(text=key),)),),
    ).model_copy(update=updates)


@pytest.mark.asyncio
async def test_stale_revision_does_not_block_append_or_invalidate_driver(running):
    runtime, store, before_turn = running
    active = await progress(store, before_turn)
    receipt = await runtime.steer_run(steer(active, expected_revision=before_turn.revision), CONTEXT)
    assert receipt.decision == CommandDecision.ACCEPTED
    current = await runtime.get_run(active.run_id)
    assert current.revision == active.revision
    assert current.last_run_sequence == active.last_run_sequence + 1
    # Execution CAS remains valid even if input arrived after the driver read.
    advanced = await progress(store, active, kind=None)
    assert advanced.revision == active.revision + 1
    # Consumption is still fenced against stale execution snapshots.
    with pytest.raises(Exception) as error:
        await store.claim_steers(run_id=active.run_id, expected_revision=active.revision,
                                 turn_id="turn_1", context=CONTEXT)
    assert error.value.info.code == "run.revision_conflict"
    claimed = await store.claim_steers(run_id=active.run_id, expected_revision=advanced.revision,
                                       turn_id="turn_1", context=CONTEXT)
    assert len(claimed.entries) == 1


@pytest.mark.asyncio
async def test_concurrent_appends_and_replays_are_ordered_and_exactly_once(running):
    runtime, store, run = running
    run = await progress(store, run)
    commands = [steer(run, f"steer_{index}") for index in range(12)]
    receipts = await asyncio.gather(*(runtime.steer_run(command, CONTEXT)
                                      for command in commands + commands))
    assert sum(receipt.decision == CommandDecision.ACCEPTED for receipt in receipts) == 12
    assert sum(receipt.decision == CommandDecision.DUPLICATE for receipt in receipts) == 12
    entries = await store.list_steers(run.run_id)
    assert [entry.inbox_sequence for entry in entries] == list(range(1, 13))
    replay = await runtime.steer_run(commands[0].model_copy(update={"expected_revision": 999}), CONTEXT)
    assert replay.decision == CommandDecision.DUPLICATE
    conflict = await runtime.steer_run(commands[0].model_copy(update={"input": commands[1].input}), CONTEXT)
    assert conflict.error.code == "idempotency.conflict"
    current = await runtime.get_run(run.run_id)
    claimed = await store.claim_steers(run_id=run.run_id, expected_revision=current.revision,
                                       turn_id="turn_1", context=CONTEXT)
    assert [entry.steer_id for entry in claimed.entries] == [entry.steer_id for entry in entries]
    claimed_again = await store.claim_steers(run_id=run.run_id, expected_revision=current.revision,
                                             turn_id="turn_1", context=CONTEXT)
    assert claimed_again.entries == ()


@pytest.mark.asyncio
async def test_requires_live_matching_turn_and_owner(running):
    runtime, store, run = running
    absent = await runtime.steer_run(steer(run), CONTEXT)
    assert absent.error.code == "steer.turn_conflict"
    run = await progress(store, run)
    wrong = await runtime.steer_run(steer(run, expected_turn_id="old_turn"), CONTEXT)
    assert wrong.error.code == "steer.turn_conflict"
    intruder = RequestContext(actor=ActorRef(principal_id="other", principal_type=PrincipalType.USER))
    denied = await runtime.steer_run(steer(run), intruder)
    assert denied.error.code == "session.actor_not_authorized"
    privileged = steer(run).model_copy(update={"input": (InputItem(
        role="system", content=(TextBlock(text="override"),)),)})
    assert (await runtime.steer_run(privileged, CONTEXT)).error.code == "session.privileged_input_role_denied"
    assert await store.list_steers(run.run_id) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED])
async def test_terminal_commit_settles_pending_and_replay_survives_restart(running, state, tmp_path):
    runtime, store, run = running
    run = await progress(store, run)
    command = steer(run)
    accepted = await runtime.steer_run(command, CONTEXT)
    await progress(store, run, kind=None, state=state)
    if isinstance(store, FilesystemSessionStore):
        await store.close()
        store = FilesystemSessionStore(tmp_path / "runtime.db")
        runtime = HarnessRuntime(cast(SessionStore, store))
    try:
        entries = await store.list_steers(run.run_id)
        assert entries[0].status.value == "rejected"
        assert entries[0].rejection_reason == f"run_{state.value}"
        assert entries[0].rejected_at is not None
        events = await store.read_events(run.run_id)
        rejected = [event for event in events if event.type == "steer.rejected"]
        assert len(rejected) == 1
        assert rejected[0].data.steer_id == accepted.result["steer_id"]
        replay = await runtime.steer_run(command, CONTEXT)
        assert replay.decision == CommandDecision.DUPLICATE
        late = await runtime.steer_run(steer(run, "late"), CONTEXT)
        assert late.error.code == "run.invalid_transition"
        intruder = RequestContext(actor=ActorRef(principal_id="other", principal_type=PrincipalType.USER))
        assert (await runtime.steer_run(command, intruder)).error.code == "session.actor_not_authorized"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_turn_end_rejects_pending_without_leaking_to_next_turn(running):
    runtime, store, run = running
    run = await progress(store, run)
    await runtime.steer_run(steer(run), CONTEXT)
    run = await progress(store, run, kind="turn.completed")
    assert (await store.list_steers(run.run_id))[0].rejection_reason == "turn_ended"
    assert (await runtime.steer_run(steer(run, "late"), CONTEXT)).error.code == "steer.turn_conflict"
    run = await progress(store, run, turn="turn_2")
    claimed = await store.claim_steers(run_id=run.run_id, expected_revision=run.revision,
                                       turn_id="turn_2", context=CONTEXT)
    assert claimed.entries == ()


@pytest.mark.asyncio
async def test_pause_preserves_pending_until_resume_or_cancellation(running):
    runtime, store, run = running
    run = await progress(store, run)
    await runtime.steer_run(steer(run), CONTEXT)
    run = await progress(store, run, kind=None, state=RunState.SUSPEND_REQUESTED)
    assert (await store.list_steers(run.run_id))[0].status.value == "pending"
    assert (await runtime.steer_run(steer(run, "late"), CONTEXT)).error.code == "run.invalid_transition"
    run = await progress(store, run, kind=None, state=RunState.RUNNING)
    claimed = await store.claim_steers(run_id=run.run_id, expected_revision=run.revision,
                                       turn_id="turn_1", context=CONTEXT)
    assert len(claimed.entries) == 1
    assert claimed.entries[0].status.value == "applied"
    await progress(store, claimed.run, kind=None, state=RunState.CANCELLED)
    assert (await store.list_steers(run.run_id))[0].status.value == "applied"


@pytest.mark.asyncio
async def test_checkpoint_uses_actual_event_boundary_after_inbox_append(running):
    runtime, store, run = running
    run = await progress(store, run)
    checkpoint = Checkpoint(
        checkpoint_id="checkpoint", checkpoint_codec_version="test", session_id=run.session_id,
        run_id=run.run_id, run_sequence=run.last_run_sequence + 1,
        session_revision=run.accepted_session_revision, state={"execution_checkpoint": True}, resolved_spec_hash="sha256:spec",
        created_at=utc_now(),
    )
    await runtime.steer_run(steer(run), CONTEXT)
    result = await store.commit_run(
        run_id=run.run_id, expected_revision=run.revision,
        expected_states={RunState.RUNNING}, new_state=RunState.RUNNING,
        drafts=(EventDraft(type="checkpoint.committed", data=CheckpointEventData(
            checkpoint_id=checkpoint.checkpoint_id, checkpoint_codec_version="test",
            run_sequence=checkpoint.run_sequence, session_revision=checkpoint.session_revision,
        )),), context=CONTEXT, idempotency_key="checkpoint", checkpoint=checkpoint,
    )
    persisted = await store.get_checkpoint(checkpoint.checkpoint_id)
    assert persisted.run_sequence == result.events[-1].run_sequence
    assert result.events[-1].data.run_sequence == persisted.run_sequence
    # Retrying the original pre-append checkpoint is still idempotent.
    replay = await store.commit_run(
        run_id=run.run_id, expected_revision=run.revision,
        expected_states={RunState.RUNNING}, new_state=RunState.RUNNING,
        drafts=(EventDraft(type="checkpoint.committed", data=CheckpointEventData(
            checkpoint_id=checkpoint.checkpoint_id, checkpoint_codec_version="test",
            run_sequence=checkpoint.run_sequence, session_revision=checkpoint.session_revision,
        )),), context=CONTEXT, idempotency_key="checkpoint", checkpoint=checkpoint,
    )
    assert replay.duplicate


@pytest.mark.asyncio
async def test_legacy_accepted_command_can_be_replayed_with_a_fresh_revision(running, tmp_path):
    from dataclasses import replace

    runtime, store, run = running
    run = await progress(store, run)
    command = steer(run)
    await runtime.steer_run(command, CONTEXT)
    key = (run.run_id, command.idempotency_key)
    previous = store._command_results[key]
    # Reproduce the old persisted receipt/digest: enqueue used to advance Run
    # revision and include the caller's pre-append revision in its hash.
    store._command_results[key] = replace(previous, run=previous.run.model_copy(
        update={"revision": run.revision + 1}))
    store._command_digests[key] = store._digest(command.model_copy(
        update={"expected_revision": run.revision}).model_dump(mode="json"))
    await progress(store, run, kind=None)
    if isinstance(store, FilesystemSessionStore):
        await store.close()
        store = FilesystemSessionStore(tmp_path / "runtime.db")
        runtime = HarnessRuntime(cast(SessionStore, store))
    try:
        replay = await runtime.steer_run(command.model_copy(update={"expected_revision": 999}), CONTEXT)
        assert replay.decision == CommandDecision.DUPLICATE
        changed = await runtime.steer_run(command.model_copy(update={"input": steer(run, "changed").input}), CONTEXT)
        assert changed.error.code == "idempotency.conflict"
        assert len(await store.list_steers(run.run_id)) == 1
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("end_first", [False, True])
async def test_enqueue_racing_completion_has_one_durable_outcome(running, end_first):
    runtime, store, run = running
    run = await progress(store, run)
    command = steer(run)
    operations = [runtime.steer_run(command, CONTEXT),
                  progress(store, run, kind=None, state=RunState.COMPLETED)]
    if end_first:
        operations.reverse()
    results = await asyncio.gather(*operations)
    receipt = results[1] if end_first else results[0]
    entries = await store.list_steers(run.run_id)
    if receipt.decision == CommandDecision.ACCEPTED:
        assert len(entries) == 1
        assert entries[0].status.value == "rejected"
    else:
        assert receipt.error.code == "run.invalid_transition"
        assert entries == ()
    assert all(entry.status.value != "pending" for entry in entries)
