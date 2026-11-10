"""Semantic operation boundaries: failures recover without renewing Run budgets."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.agent.policy import LLMContinuationJudge
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.model_recovery import ModelRecoveryConfig
from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.model.recovery import collect_response
from sagents.v2.model.recovery_scope import (
    RecoveryScope,
    recovery_scope,
    scoped_recovery,
    reserve_additional_request,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
from sagents.v2.tool.selection import ToolSelectionPrepareContext
from tests.sagents.v2.test_builtin_model_protocols_matrix import request
from tests.sagents.v2.test_continuation_judge_matrix import _context
from tests.sagents.v2.test_tool_selection_matrix import TOOLS


def response(text, finish="stop"):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(response_id="fixture", text=text, finish_reason=finish),
    )


def model(*outputs):
    return ScriptedModelProvider(
        tuple(
            ScriptedModelStep(events=(response(text, finish),))
            for text, finish in outputs
        )
    )


async def no_wait(self, seconds):
    if self.check:
        await self.check()


@pytest.mark.parametrize("purpose", ["judge", "memory", "selection"])
async def test_auxiliary_request_timeout_recovers_locally(purpose, monkeypatch):
    monkeypatch.setattr(RecoveryScope, "wait", no_wait)
    text = {
        "judge": '{"decision":"completed","reason":"done"}',
        "memory": '{"query":"known"}',
        "selection": '{"tools":[]}',
    }[purpose]

    class SlowFirst:
        calls = 0
        closed = 0

        async def stream(self, request):
            self.calls += 1
            try:
                if self.calls == 1:
                    await asyncio.sleep(10)
                yield response(text)
            finally:
                self.closed += 1

    provider = SlowFirst()
    scope = RecoveryScope()
    with recovery_scope(scope):
        if purpose == "judge":
            result = await LLMContinuationJudge(provider, timeout_seconds=0.01).decide(
                _context()
            )
            assert result.reason_code != "judge.invalid_output"
        elif purpose == "memory":
            assert (
                await LLMMemoryRecallQueryGenerator(
                    provider, timeout_seconds=0.01
                ).generate("task", run_id="r")
                == "known"
            )
        else:
            await LLMToolSelectionPolicy(
                {"max_visible_tools": 2, "model_timeout_seconds": 0.01}
            ).prepare(
                ToolSelectionPrepareContext(run_id="r", tools=TOOLS, model=provider)
            )
    assert provider.calls == provider.closed == 2
    assert scope.run_requests == 1
    assert not scope.episode_deadlines


@pytest.mark.parametrize("bad", ["not json", '{"query":3}', '{"missing":"query"}'])
async def test_memory_output_repairs_its_contract(bad):
    provider = model((bad, "stop"), ('{"query":"known"}', "stop"))
    assert (
        await LLMMemoryRecallQueryGenerator(provider).generate("task", run_id="r")
        == "known"
    )
    assert len(provider.requests) == 2
    assert provider.requests[1].messages[-1].metadata["inference_view_only"]


async def test_memory_invalid_output_stops_after_two_corrections():
    provider = model(*[("bad", "stop")] * 4)
    with pytest.raises(SageV2Error) as caught:
        await LLMMemoryRecallQueryGenerator(provider).generate("task", run_id="r")
    assert caught.value.info.code == "model.structured_output_invalid"
    assert len(provider.requests) == 3


@pytest.mark.parametrize("text", ['{"tools":[', '{"tools":[]}'])
async def test_truncated_selection_requires_complete_regeneration(text):
    provider = model((text, "length"), ('{"tools":[]}', "stop"))
    await LLMToolSelectionPolicy({"max_visible_tools": 2}).prepare(
        ToolSelectionPrepareContext(run_id="r", tools=TOOLS, model=provider)
    )
    assert len(provider.requests) == 2
    assert "shorter" in provider.requests[1].messages[-1].content[0].text


async def test_success_closes_episode_but_preserves_run_budget():
    now = [datetime.now(timezone.utc)]
    scope = RecoveryScope(
        clock=lambda: now[0], config=ModelRecoveryConfig(run_requests=1)
    )
    provider = model(
        ("", "stop"), ("recovered", "stop"), ("next", "stop"), ("", "stop")
    )
    events = []

    async def persist(key, state, error, decision):
        events.append((key, state, error, decision))

    scope.persist = persist
    with recovery_scope(scope):
        await collect_response(provider, request(), purpose="first")
        assert not scope.episode_deadlines
        assert events[-1][2].metadata["episode_closed"]
        now[0] += timedelta(seconds=121)
        assert (
            await collect_response(provider, request(), purpose="second")
        ).text == "next"
        with pytest.raises(SageV2Error):
            await collect_response(provider, request(), purpose="third")
    assert scope.run_requests == 1
    assert len(provider.requests) == 4


async def test_nested_success_does_not_reset_unfinished_repair_budget():
    scope = RecoveryScope(config=ModelRecoveryConfig(episode_requests=1))
    provider = model(("", "stop"), ("usable", "stop"))

    @scoped_recovery
    async def outer():
        await collect_response(provider, request())
        assert scope.episode_counts[scope.step_key] == 1
        await reserve_additional_request("arguments", purpose="semantic_validation")

    with recovery_scope(scope), pytest.raises(SageV2Error):
        await outer()
    assert scope.run_requests == 1


async def test_episode_deadline_is_not_retried_as_request_timeout(monkeypatch):
    monkeypatch.setattr(RecoveryScope, "wait", no_wait)

    class SlowRecovery:
        calls = 0

        async def stream(self, req):
            self.calls += 1
            if self.calls == 1:
                yield response("")
            else:
                await asyncio.sleep(10)
                yield response("unreachable")

    provider = SlowRecovery()
    scope = RecoveryScope(config=ModelRecoveryConfig(episode_seconds=0.02))
    with recovery_scope(scope), pytest.raises(SageV2Error) as caught:
        await collect_response(provider, request(), request_timeout_seconds=1)
    assert caught.value.info.code == "model.recovery_exhausted"
    assert provider.calls == 2


async def test_cancel_during_auxiliary_call_never_retries():
    class Pending:
        calls = 0
        entered = asyncio.Event()

        async def stream(self, request):
            self.calls += 1
            self.entered.set()
            await asyncio.sleep(10)
            yield response("unreachable")

    provider = Pending()
    task = asyncio.create_task(
        collect_response(provider, request(), request_timeout_seconds=1)
    )
    await provider.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.calls == 1


async def test_episode_completion_survives_restart_and_stale_checkpoint():
    from tests.sagents.v2 import test_agent_loop_matrix as native
    from sagents.v2.model.recovery_scope import current_recovery_scope
    from sagents.v2.agent.policy import ContinuationDecision, ContinuationAction

    saved = []

    class CloseDuringRun:
        async def decide(self, context):
            scope = current_recovery_scope()
            await reserve_additional_request("arguments", purpose="validator")
            old_state = scope.states[f"{scope.step_key}:validator"].model_copy(
                update={"logical_call_id": scope.step_key}
            )
            saved.append(
                native.AgentLoopCheckpointState(
                    turn_id="turn_test", step_number=1, model_recovery=old_state
                )
            )
            await scope.finish_episode()
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="test.done",
                reason="done",
            )

    runtime, handle, loop, _ = await native.setup_loop(
        model(("done", "stop")), continuation_policy=CloseDuringRun()
    )
    await loop.execute(handle.run_id, native.CONTEXT)
    command = await runtime.session_store.get_start_command(handle.run_id)
    # The durable close wins even if the older host checkpoint still has counts.
    restored = await loop._create_recovery_scope(
        await runtime.get_run(handle.run_id), saved[0], command, native.CONTEXT
    )
    assert restored.run_requests == 1
    assert not restored.episode_deadlines
    assert not restored.episode_counts
    assert not restored.states


async def test_successful_main_recovery_does_not_expire_later_judge():
    from tests.sagents.v2 import test_agent_loop_matrix as native

    now = [datetime.now(timezone.utc)]
    provider = model(("", "stop"), ("done", "stop"))
    judge_model = model(('{"decision":"completed","reason":"done"}', "stop"))
    judge = LLMContinuationJudge(judge_model)

    class LaterJudge:
        async def decide(self, context):
            now[0] += timedelta(seconds=121)
            return await judge.decide(context)

    runtime, handle, loop, _ = await native.setup_loop(
        provider, continuation_policy=LaterJudge(), clock=lambda: now[0]
    )
    result = await loop.execute(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.COMPLETED
    assert len(provider.requests) == 2
    assert len(judge_model.requests) == 1
    events = await runtime.session_store.read_events(handle.run_id)
    assert any(
        getattr(e.data, "error", None) and e.data.error.metadata.get("episode_closed")
        for e in events
    )


async def test_pending_primary_recovery_keeps_nested_summary_budget():
    scope = RecoveryScope(primary_recovery=True)
    provider = model(("", "stop"), ("summary", "stop"))
    with recovery_scope(scope):
        await collect_response(provider, request(), purpose="conversation_summary")
    assert scope.episode_counts[scope.step_key] == 1
    assert scope.episode_deadlines[scope.step_key] is not None
