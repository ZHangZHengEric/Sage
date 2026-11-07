from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.v2.server.conversations import external_runs
from sagents.v2.contracts.items import UsageSummary
from sagents.v2.contracts.run_state import RunState


@pytest.mark.parametrize("timeline, expected", [
    ([("run.started", 10), ("run.completed", 40)], 30000),
    ([("run.started", 10), ("run.suspended", 20), ("run.resumed", 80), ("run.completed", 90)], 20000),
    ([("run.started", 10), ("run.resumed", 11), ("run.failed", 40)], 30000),
    ([("run.completed", 40)], None),
    ([("run.started", 40), ("run.completed", 10)], None),
])
async def test_run_metrics_excludes_queue_and_suspension(monkeypatch, timeline, expected):
    start = datetime(2026, 11, 7, tzinfo=timezone.utc)
    events = tuple(SimpleNamespace(type=kind, run_sequence=i+1,
        occurred_at=start+timedelta(seconds=seconds)) for i, (kind, seconds) in enumerate(timeline))
    access = SimpleNamespace(
        get_run=AsyncMock(return_value=SimpleNamespace(state=RunState.COMPLETED, created_at=start)),
        get_run_result=AsyncMock(return_value=SimpleNamespace(completed_at=start+timedelta(seconds=90),
            usage=UsageSummary(reported=True, input_tokens=100, output_tokens=25, cached_input_tokens=40,
                               provider_usage={"private": "must not leave Sage"}))),
        read_events=AsyncMock(side_effect=[events, ()]),
    )
    selected = AsyncMock(return_value=({}, "native", None, None, "context", access, None))
    monkeypatch.setattr(external_runs, "selected_run", selected)
    result = await external_runs.run_metrics(None, tenant_id="tenant", agent_id="agent", thread_id="thread", run_id="run")
    assert result["activeMilliseconds"] == expected
    assert result["usage"] == {"reported": True, "input_tokens": 100, "output_tokens": 25, "cached_input_tokens": 40}
    assert result["runId"] == "run" and result["threadId"] == "thread"
    selected.assert_awaited_once_with(None, tenant_id="tenant", agent_id="agent", thread_id="thread", run_id="run")
    assert access.read_events.await_args_list[1].kwargs["after_sequence"] == len(events)


async def test_running_metrics_remain_unknown(monkeypatch):
    access = SimpleNamespace(get_run=AsyncMock(return_value=SimpleNamespace(
        state=RunState.RUNNING, created_at=datetime.now(timezone.utc))))
    monkeypatch.setattr(external_runs, "selected_run", AsyncMock(return_value=({}, "native", None, None, "context", access, None)))
    result = await external_runs.run_metrics(None, tenant_id="tenant", agent_id="agent", thread_id="thread", run_id="run")
    assert result["usage"] is None and result["activeMilliseconds"] is None and result["completedAt"] is None
