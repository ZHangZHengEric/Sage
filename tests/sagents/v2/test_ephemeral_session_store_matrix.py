from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.contracts.checkpoint import (
    Checkpoint,
    Suspension,
    SuspensionReason,
)
from sagents.v2.contracts.commands import (
    CancelRun,
    CommandDecision,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.interactions import (
    BlockingScope,
    InteractionRequest,
    InteractionType,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunState,
    SessionConcurrencyMode,
)
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
ACTOR = ActorRef(
    principal_id="user_test",
    principal_type=PrincipalType.USER,
    tenant_id="tenant_test",
)
CONTEXT = RequestContext(
    actor=ACTOR,
    trace=TraceContext(correlation_id="correlation_test"),
)


def start_command(
    key: str,
    *,
    session_id: str | None = None,
    mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL,
    base_revision: int | None = None,
) -> StartRun:
    return StartRun(
        session_id=session_id,
        agent_id="agent_test",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        session_concurrency_mode=mode,
        base_session_revision=base_revision,
        resolved_spec_hash="sha256:spec",
        idempotency_key=key,
    )


async def running_runtime() -> tuple[HarnessRuntime, str, str]:
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(start_command("start_1"), CONTEXT)
    run = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=CONTEXT,
        idempotency_key="execute_1",
    )
    assert run.state == RunState.RUNNING
    return runtime, handle.session_id, handle.run_id


@pytest.mark.asyncio
async def test_start_is_idempotent_and_returns_same_handle_without_new_events():
    repository = EphemeralSessionStore()
    first = await repository.create_run(start_command("request_1"), CONTEXT)
    second = await repository.create_run(start_command("request_1"), CONTEXT)

    assert second.duplicate is True
    assert second.handle == first.handle
    assert second.events == ()
    assert [event.type for event in first.events] == [
        "run.accepted",
        "run.queued",
        "message.completed",
    ]
    input_event = first.events[-1]
    assert input_event.source.source_type.value == "user"
    assert input_event.data.item.data.role == "user"
    assert input_event.data.item.data.content[0].text == "hello"
    assert [event.run_sequence for event in first.events] == [1, 2, 3]
    assert [event.session_sequence for event in first.events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_run_ids_are_timestamped_and_lexically_sortable():
    current_time = [datetime(2026, 8, 25, 1, 2, 3, 456789, tzinfo=timezone.utc)]
    repository = EphemeralSessionStore(clock=lambda: current_time[0])

    first = await repository.create_run(start_command("request_1"), CONTEXT)
    current_time[0] = datetime(2026, 8, 25, 1, 2, 4, 123456, tzinfo=timezone.utc)
    second = await repository.create_run(start_command("request_2"), CONTEXT)

    assert first.handle.run_id.startswith("run_20260825T010203456789Z_")
    assert second.handle.run_id.startswith("run_20260825T010204123456Z_")
    assert first.handle.run_id < second.handle.run_id


@pytest.mark.asyncio
async def test_serial_mode_rejects_parallel_active_run_and_releases_after_terminal():
    runtime = ephemeral_runtime()
    first = await runtime.start_run(
        start_command("start_1", session_id="session_1"), CONTEXT
    )

    with pytest.raises(SageV2Error) as exc_info:
        await runtime.start_run(
            start_command("start_2", session_id="session_1"), CONTEXT
        )
    assert exc_info.value.info.code == "session.serial_run_active"

    receipt = await runtime.cancel_run(
        CancelRun(
            run_id=first.run_id,
            expected_revision=first.run_revision,
            idempotency_key="cancel_1",
        ),
        CONTEXT,
    )
    assert receipt.decision == CommandDecision.ACCEPTED
    second = await runtime.start_run(
        start_command("start_2", session_id="session_1"), CONTEXT
    )
    assert second.run_id != first.run_id


@pytest.mark.asyncio
async def test_snapshot_isolated_mode_allows_stale_base_and_concurrent_runs():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(
        start_command("seed", session_id="session_1"), CONTEXT
    )
    await runtime.cancel_run(
        CancelRun(
            run_id=seed.run_id,
            expected_revision=0,
            idempotency_key="cancel_seed",
        ),
        CONTEXT,
    )
    session = await runtime.session_store.get_session("session_1")

    first, second = await asyncio.gather(
        runtime.start_run(
            start_command(
                "snapshot_1",
                session_id="session_1",
                mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                base_revision=session.revision,
            ),
            CONTEXT,
        ),
        runtime.start_run(
            start_command(
                "snapshot_2",
                session_id="session_1",
                mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                base_revision=session.revision,
            ),
            CONTEXT,
        ),
    )
    assert first.run_id != second.run_id
    assert (
        first.base_session_revision == second.base_session_revision == session.revision
    )


@pytest.mark.asyncio
async def test_serial_rejects_stale_and_all_modes_reject_future_base_revision():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(
        start_command("seed", session_id="session_1"), CONTEXT
    )
    await runtime.cancel_run(
        CancelRun(run_id=seed.run_id, expected_revision=0, idempotency_key="cancel"),
        CONTEXT,
    )
    session = await runtime.session_store.get_session("session_1")

    with pytest.raises(SageV2Error) as stale:
        await runtime.start_run(
            start_command("stale", session_id="session_1", base_revision=0), CONTEXT
        )
    assert stale.value.info.code == "session.revision_conflict"

    with pytest.raises(SageV2Error) as future:
        await runtime.start_run(
            start_command(
                "future",
                session_id="session_1",
                mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                base_revision=session.revision + 1,
            ),
            CONTEXT,
        )
    assert future.value.info.code == "session.revision_in_future"


@pytest.mark.asyncio
async def test_fork_has_new_session_and_preserves_parent_lineage():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(start_command("parent"), CONTEXT)
    fork = await runtime.start_run(
        start_command(
            "fork",
            session_id=parent.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )
    fork_session = await runtime.session_store.get_session(fork.session_id)

    assert fork.session_id != parent.session_id
    assert fork_session.parent_session_id == parent.session_id
    assert fork.base_session_revision == parent.accepted_session_revision


@pytest.mark.asyncio
async def test_delete_parent_requires_terminal_tree_and_removes_descendants():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(start_command("delete-parent"), CONTEXT)
    child = await runtime.start_run(
        start_command(
            "delete-child",
            session_id=parent.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )

    with pytest.raises(SageV2Error) as active:
        await runtime.session_store.delete_session(parent.session_id)
    assert active.value.info.code == "session.active_run"
    assert active.value.info.metadata == {
        "root_session_id": parent.session_id,
        "active_run_ids": sorted([parent.run_id, child.run_id]),
        "active_session_ids": sorted([parent.session_id, child.session_id]),
    }

    for handle, key in ((parent, "cancel-parent"), (child, "cancel-child")):
        await runtime.cancel_run(
            CancelRun(
                run_id=handle.run_id,
                expected_revision=handle.run_revision,
                idempotency_key=key,
            ),
            CONTEXT,
        )
    await runtime.session_store.delete_session(parent.session_id)

    for session_id in (parent.session_id, child.session_id):
        with pytest.raises(SageV2Error) as missing:
            await runtime.session_store.get_session(session_id)
        assert missing.value.info.code == "session.not_found"


@pytest.mark.asyncio
async def test_stale_run_revision_rejected_but_same_command_key_is_duplicate():
    runtime, _, run_id = await running_runtime()
    accepted = await runtime.pause_run(
        PauseRun(run_id=run_id, expected_revision=1, idempotency_key="pause_1"),
        CONTEXT,
    )
    duplicate = await runtime.pause_run(
        PauseRun(run_id=run_id, expected_revision=1, idempotency_key="pause_1"),
        CONTEXT,
    )
    stale = await runtime.pause_run(
        PauseRun(run_id=run_id, expected_revision=1, idempotency_key="pause_2"),
        CONTEXT,
    )

    assert accepted.decision == CommandDecision.ACCEPTED
    assert duplicate.decision == CommandDecision.DUPLICATE
    assert stale.decision == CommandDecision.REJECTED
    assert stale.error is not None and stale.error.code == "run.revision_conflict"
    recovery = stale.error.metadata["recovery_questionnaire"]
    assert recovery["questions"]
    assert recovery["language"] == "en"


def suspension_records(
    session_id: str, run_id: str, *, checkpoint_run_id: str | None = None
):
    checkpoint = Checkpoint(
        checkpoint_id="checkpoint_1",
        checkpoint_codec_version="1",
        session_id=session_id,
        run_id=checkpoint_run_id or run_id,
        run_sequence=4,
        session_revision=2,
        state={"turn": 1, "pending_tool_calls": []},
        resolved_spec_hash="sha256:spec",
        created_at=NOW,
    )
    interaction = InteractionRequest(
        interaction_id="interaction_1",
        run_id=run_id,
        interaction_type=InteractionType.APPROVAL,
        blocking_scope=BlockingScope.RUN,
        allowed_decisions=("approve", "reject"),
        eligible_principal_ids=("user_test",),
        payload={"tool_name": "shell"},
        requested_at=NOW,
    )
    suspension = Suspension(
        suspension_id="suspension_1",
        run_id=run_id,
        reason=SuspensionReason.APPROVAL_REQUIRED,
        blocking_scope="run",
        checkpoint_id=checkpoint.checkpoint_id,
        checkpoint_sequence=checkpoint.run_sequence,
        interaction_id=interaction.interaction_id,
        resume_policy="after_interaction_resolution",
        requested_at=NOW,
    )
    return checkpoint, interaction, suspension


@pytest.mark.asyncio
async def test_suspension_commits_checkpoint_interaction_and_events_atomically():
    runtime, session_id, run_id = await running_runtime()
    checkpoint, interaction, suspension = suspension_records(session_id, run_id)

    run = await runtime.commit_suspension(
        run_id=run_id,
        expected_revision=1,
        checkpoint=checkpoint,
        suspension=suspension,
        interaction=interaction,
        context=CONTEXT,
        idempotency_key="suspend_1",
    )
    events = await runtime.session_store.read_events(run_id)

    assert run.state == RunState.SUSPENDED
    assert run.suspension_id == suspension.suspension_id
    assert (
        await runtime.session_store.get_checkpoint(checkpoint.checkpoint_id)
        == checkpoint
    )
    assert (
        await runtime.session_store.get_interaction(interaction.interaction_id)
        == interaction
    )
    assert [event.type for event in events[-3:]] == [
        "interaction.requested",
        "checkpoint.committed",
        "run.suspended",
    ]
    assert all(event.session_sequence is not None for event in events[-3:])


@pytest.mark.asyncio
async def test_invalid_checkpoint_fails_without_mutating_run_session_or_event_log():
    runtime, session_id, run_id = await running_runtime()
    checkpoint, interaction, suspension = suspension_records(
        session_id, run_id, checkpoint_run_id="another_run"
    )
    before_run = await runtime.get_run(run_id)
    before_session = await runtime.session_store.get_session(session_id)
    before_events = await runtime.session_store.read_events(run_id)

    with pytest.raises(ValueError, match="checkpoint identity"):
        await runtime.commit_suspension(
            run_id=run_id,
            expected_revision=1,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=CONTEXT,
            idempotency_key="bad_suspend",
        )

    assert await runtime.get_run(run_id) == before_run
    assert await runtime.session_store.get_session(session_id) == before_session
    assert await runtime.session_store.read_events(run_id) == before_events


@pytest.mark.asyncio
async def test_job_pause_uses_durable_prepare_state_before_terminal_suspend_commit(
    monkeypatch,
):
    runtime, session_id, run_id = await running_runtime()
    checkpoint, interaction, suspension = suspension_records(session_id, run_id)

    class Jobs:
        def __init__(self):
            self.paused = False

        async def handle_run_pause(self, requested_run_id):
            assert requested_run_id == run_id
            self.paused = True
            return ()

    jobs = Jobs()
    runtime.job_runtime = jobs
    original_commit = runtime.session_store.commit_run

    async def fail_final_commit(**kwargs):
        if kwargs["new_state"] == RunState.SUSPENDED:
            raise OSError("final suspension write failed")
        return await original_commit(**kwargs)

    monkeypatch.setattr(runtime.session_store, "commit_run", fail_final_commit)

    with pytest.raises(OSError, match="final suspension write failed"):
        await runtime.commit_suspension(
            run_id=run_id,
            expected_revision=1,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=CONTEXT,
            idempotency_key="suspend-with-jobs",
        )

    assert jobs.paused is True
    prepared = await runtime.get_run(run_id)
    assert prepared.state == RunState.SUSPEND_REQUESTED
    assert (await runtime.session_store.read_events(run_id))[-1].type == (
        "run.pause_requested"
    )


@pytest.mark.asyncio
async def test_job_pause_backend_failure_settles_run_as_failed():
    runtime, session_id, run_id = await running_runtime()
    checkpoint, interaction, suspension = suspension_records(session_id, run_id)

    class Jobs:
        async def handle_run_pause(self, requested_run_id):
            assert requested_run_id == run_id
            raise OSError("pause backend unavailable")

    runtime.job_runtime = Jobs()
    failed = await runtime.commit_suspension(
        run_id=run_id,
        expected_revision=1,
        checkpoint=checkpoint,
        suspension=suspension,
        interaction=interaction,
        context=CONTEXT,
        idempotency_key="suspend-pause-failure",
    )

    assert failed.state == RunState.FAILED
    result = await runtime.session_store.get_run_result(run_id)
    assert result.error is not None
    assert result.error.code == "job.pause_failed"
    assert [
        event.type for event in await runtime.session_store.read_events(run_id)
    ][-2:] == ["run.pause_requested", "run.failed"]


@pytest.mark.asyncio
async def test_job_pause_cancellation_does_not_strand_suspend_requested():
    runtime, session_id, run_id = await running_runtime()
    checkpoint, interaction, suspension = suspension_records(session_id, run_id)
    entered = asyncio.Event()

    class Jobs:
        async def handle_run_pause(self, requested_run_id):
            assert requested_run_id == run_id
            entered.set()
            await asyncio.Event().wait()

    runtime.job_runtime = Jobs()
    task = asyncio.create_task(
        runtime.commit_suspension(
            run_id=run_id,
            expected_revision=1,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=CONTEXT,
            idempotency_key="suspend-pause-cancelled",
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await runtime.get_run(run_id)).state == RunState.FAILED
    result = await runtime.session_store.get_run_result(run_id)
    assert result.error is not None
    assert result.error.code == "job.pause_failed"


@pytest.mark.asyncio
async def test_pause_resume_requires_matching_suspension_and_preserves_replay_history():
    runtime, session_id, run_id = await running_runtime()
    pause = await runtime.pause_run(
        PauseRun(run_id=run_id, expected_revision=1, idempotency_key="pause"), CONTEXT
    )
    checkpoint, interaction, suspension = suspension_records(session_id, run_id)
    suspended = await runtime.commit_suspension(
        run_id=run_id,
        expected_revision=pause.current_revision,
        checkpoint=checkpoint,
        suspension=suspension,
        interaction=interaction,
        context=CONTEXT,
        idempotency_key="suspend",
    )

    wrong = await runtime.resume_run(
        ResumeRun(
            run_id=run_id,
            suspension_id="wrong_suspension",
            expected_suspension_revision=0,
            expected_revision=suspended.revision,
            idempotency_key="resume_wrong",
        ),
        CONTEXT,
    )
    assert wrong.decision == CommandDecision.REJECTED
    assert wrong.error is not None and wrong.error.code == "run.suspension_conflict"

    accepted = await runtime.resume_run(
        ResumeRun(
            run_id=run_id,
            suspension_id=suspension.suspension_id,
            expected_suspension_revision=0,
            expected_revision=suspended.revision,
            idempotency_key="resume",
        ),
        CONTEXT,
    )
    assert accepted.decision == CommandDecision.ACCEPTED
    resumed = await runtime.mark_resumed(
        run_id=run_id,
        expected_revision=accepted.current_revision,
        context=CONTEXT,
        idempotency_key="resumed",
    )
    assert resumed.state == RunState.RUNNING
    assert resumed.suspension_id is None
    assert "run.suspended" in [
        event.type for event in await runtime.session_store.read_events(run_id)
    ]


async def suspended_for_interaction(
    *,
    eligible_principals: tuple[str, ...] = ("user_test",),
    expires_at: datetime | None = None,
) -> tuple[HarnessRuntime, object, InteractionRequest, Suspension]:
    runtime, session_id, run_id = await running_runtime()
    checkpoint, interaction, suspension = suspension_records(session_id, run_id)
    interaction = interaction.model_copy(
        update={
            "eligible_principal_ids": eligible_principals,
            "expires_at": expires_at,
        }
    )
    run = await runtime.commit_suspension(
        run_id=run_id,
        expected_revision=1,
        checkpoint=checkpoint,
        suspension=suspension,
        interaction=interaction,
        context=CONTEXT,
        idempotency_key="suspend",
    )
    return runtime, run, interaction, suspension


def reply_command(run, interaction, suspension, key: str, decision: str = "approve"):
    return ReplyInteraction(
        run_id=run.run_id,
        suspension_id=suspension.suspension_id,
        interaction_id=interaction.interaction_id,
        expected_revision=run.revision,
        expected_suspension_revision=suspension.expected_revision,
        expected_interaction_revision=interaction.expected_revision,
        decision=decision,
        payload={"note": "reviewed"},
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_interaction_reply_atomically_resolves_and_schedules_resume():
    runtime, run, interaction, suspension = await suspended_for_interaction()
    command = reply_command(run, interaction, suspension, "reply_1")

    accepted = await runtime.reply_interaction(command, CONTEXT)
    duplicate = await runtime.reply_interaction(command, CONTEXT)
    updated_run = await runtime.get_run(run.run_id)
    updated_interaction = await runtime.session_store.get_interaction(
        interaction.interaction_id
    )
    updated_suspension = await runtime.session_store.get_suspension(
        suspension.suspension_id
    )
    resolution = await runtime.session_store.get_interaction_resolution(
        interaction.interaction_id
    )

    assert accepted.decision == CommandDecision.ACCEPTED
    assert duplicate.decision == CommandDecision.DUPLICATE
    assert updated_run.state == RunState.RESUMING
    assert updated_interaction.status.value == "resolved"
    assert updated_interaction.expected_revision == 1
    assert updated_suspension.status.value == "resolving"
    assert updated_suspension.expected_revision == 1
    assert resolution.decision == "approve"
    assert [
        event.type
        for event in (await runtime.session_store.read_events(run.run_id))[-2:]
    ] == ["interaction.resolved", "run.resume_requested"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "eligible", "expired", "error_code"),
    [
        ("invalid", ("user_test",), False, "interaction.decision_not_allowed"),
        ("approve", ("another_user",), False, "interaction.principal_not_eligible"),
        ("approve", ("user_test",), True, "interaction.expired"),
    ],
)
async def test_interaction_reply_rejection_matrix_has_no_partial_mutation(
    decision, eligible, expired, error_code
):
    runtime, run, interaction, suspension = await suspended_for_interaction(
        eligible_principals=eligible,
        expires_at=NOW - timedelta(seconds=1) if expired else None,
    )
    before_events = await runtime.session_store.read_events(run.run_id)

    receipt = await runtime.reply_interaction(
        reply_command(run, interaction, suspension, "reply_bad", decision), CONTEXT
    )

    assert receipt.decision == CommandDecision.REJECTED
    assert receipt.error is not None and receipt.error.code == error_code
    assert (await runtime.get_run(run.run_id)).state == RunState.SUSPENDED
    assert await runtime.session_store.read_events(run.run_id) == before_events
    assert (
        await runtime.session_store.get_interaction(interaction.interaction_id)
    ).status.value == "pending"


@pytest.mark.asyncio
async def test_concurrent_interaction_replies_have_single_winner():
    runtime, run, interaction, suspension = await suspended_for_interaction()
    first, second = await asyncio.gather(
        runtime.reply_interaction(
            reply_command(run, interaction, suspension, "reply_1", "approve"), CONTEXT
        ),
        runtime.reply_interaction(
            reply_command(run, interaction, suspension, "reply_2", "reject"), CONTEXT
        ),
    )
    assert sorted([first.decision.value, second.decision.value]) == [
        "accepted",
        "rejected",
    ]
    assert (
        len(
            [
                event
                for event in await runtime.session_store.read_events(run.run_id)
                if event.type == "interaction.resolved"
            ]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_replay_then_live_subscription_and_detach():
    runtime, _, run_id = await running_runtime()
    replay = await runtime.session_store.read_events(run_id)
    stream = runtime.subscribe_events(
        EventCursor(run_id=run_id, run_sequence=len(replay) - 1)
    )
    assert (await anext(stream)).event_id == replay[-1].event_id

    next_event = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    receipt = await runtime.steer_run(
        SteerRun(
            run_id=run_id,
            expected_revision=1,
            expected_turn_id="turn_1",
            input=(InputItem(role="user", content=(TextBlock(text="adjust"),)),),
            idempotency_key="steer_1",
        ),
        CONTEXT,
    )
    assert receipt.decision == CommandDecision.ACCEPTED
    assert (await next_event).type == "steer.accepted"
    await stream.aclose()


@pytest.mark.asyncio
async def test_slow_subscriber_gets_resumable_overflow_not_silent_loss():
    repository = EphemeralSessionStore(subscriber_queue_size=1)
    runtime = HarnessRuntime(repository)
    handle = await runtime.start_run(start_command("start"), CONTEXT)
    stream = runtime.subscribe_events(
        EventCursor(run_id=handle.run_id, run_sequence=handle.event_cursor.run_sequence)
    )
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="execute",
    )
    await runtime.pause_run(
        PauseRun(run_id=handle.run_id, expected_revision=1, idempotency_key="pause"),
        CONTEXT,
    )

    with pytest.raises(SageV2Error) as overflow:
        await waiting
    assert overflow.value.info.code == "stream.subscriber_overflow"
    assert overflow.value.info.retryable is True
    assert overflow.value.info.safe_to_resume is True
    await stream.aclose()
