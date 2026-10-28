"""Cancelling an approval stops the Run; denying only skips that operation."""

import pytest

from sagents.v2.contracts.run_state import RunState
from sagents.v2.contracts.commands import PauseRun, CancelRun
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
from tests.sagents.v2.test_agent_loop_matrix import (
    CONTEXT,
    _approval_reply,
    _pending_interaction,
    _write_call,
    completed,
    setup_loop,
)


@pytest.mark.parametrize(
    ("decision", "race"),
    [
        ("cancel", None),
        ("deny", None),
        ("cancel", "pause"),
        ("cancel", "external_cancel"),
    ],
)
async def test_approval_cancel_stops_before_another_model_request(
    decision, race, monkeypatch
):
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(_write_call("write"),)),)),
            ScriptedModelStep(events=(completed("A final answer after denial"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model)
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, suspended)
    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id, suspended, suspension, interaction, decision, "answer"
        ),
        CONTEXT,
    )
    if race:
        original_cancel = runtime.cancel_run
        interrupted = False

        async def concurrent_control(command, context):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                if race == "pause":
                    receipt = await runtime.pause_run(
                        PauseRun(
                            run_id=command.run_id,
                            expected_revision=command.expected_revision,
                            idempotency_key="concurrent-pause",
                            reason="fixture",
                        ),
                        context,
                    )
                else:
                    receipt = await original_cancel(
                        CancelRun(
                            run_id=command.run_id,
                            expected_revision=command.expected_revision,
                            idempotency_key="concurrent-cancel",
                            reason="fixture",
                        ),
                        context,
                    )
                assert receipt.error is None
            return await original_cancel(command, context)

        monkeypatch.setattr(runtime, "cancel_run", concurrent_control)
    result = await loop.resume(handle.run_id, CONTEXT)
    assert result.state == (
        RunState.CANCELLED if decision == "cancel" else RunState.COMPLETED
    )
    assert len(model.requests) == (1 if decision == "cancel" else 2)
    assert not executor.calls
