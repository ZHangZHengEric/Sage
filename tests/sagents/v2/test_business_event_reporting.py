from contextlib import asynccontextmanager
from datetime import timedelta

import pytest

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.events import RunEventData, ToolEventData, UsageEventData
from sagents.v2.contracts.items import UsageSummary
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.observability.performance.aggregation import timing_report
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from tests.sagents.v2.sql_storage_fixture import sql_store_factory
from tests.sagents.v2.test_sql_session_store_contract import CONTEXT, command


@asynccontextmanager
async def open_filesystem(root):
    store = FilesystemSessionStore(root)
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.parametrize("backend", ["filesystem", "postgres", "mysql", "redis-postgres", "redis-mysql"])
async def test_business_report_replays_committed_events_after_reopen(backend, tmp_path):
    async def exercise(store):
        accepted = await store.create_run(command(), CONTEXT)
        handle = accepted.handle
        running = await store.commit_run(
            run_id=handle.run_id, expected_revision=handle.run_revision,
            expected_states={RunState.QUEUED}, new_state=RunState.RUNNING,
            drafts=(EventDraft(type="run.started", data=RunEventData(state="running")),),
            context=CONTEXT, idempotency_key="report-start",
        )
        tool = {"tool_call_id": "call", "tool_name": "test", "operation_id": "operation"}
        options = dict(
            run_id=handle.run_id, expected_revision=running.run.revision,
            expected_states={RunState.RUNNING}, new_state=RunState.COMPLETED,
            drafts=(
                EventDraft(type="tool.call.started", data=ToolEventData(state="started", **tool)),
                EventDraft(type="tool.call.unknown", data=ToolEventData(state="unknown", **tool)),
                EventDraft(type="tool.call.reconciled", data=ToolEventData(state="completed", **tool)),
                EventDraft(type="usage.recorded", data=UsageEventData(
                    usage=UsageSummary(reported=True, input_tokens=9, output_tokens=4, cached_input_tokens=2),
                )),
                EventDraft(type="run.completed", data=RunEventData(state="completed")),
            ),
            context=CONTEXT, idempotency_key="report-finish",
        )
        await store.commit_run(**options)
        assert (await store.commit_run(**options)).duplicate
        await store.create_run(command().model_copy(update={"idempotency_key": "queued", "agent_id": "other"}), CONTEXT)
        return handle

    async def verify(store, handle):
        now = utc_now()
        start, end = (now - timedelta(minutes=1)).timestamp(), (now + timedelta(minutes=1)).timestamp()
        replay = await store.report_business_events(start=start, end=end)
        assert not replay.cohort_truncated and not replay.events_truncated and not replay.archive_pending
        assert len(replay.runs) == 2
        facts = replay.runs[handle.session_id, handle.run_id]
        assert facts.tools == {("operation",): "reconciled"}
        assert facts.usage_records == facts.reported_usage_records == 1
        assert facts.tokens["input_tokens"] == 9
        report = timing_report({}, {}, start=start, end=end, business=replay)
        assert report["summary"]["run_states"] == {"completed": 1, "queued": 1}
        assert report["summary"]["coverage_rate"] == 0
        assert report["summary"]["tool_outcomes"] == {"reconciled": 1}
        assert report["summary"]["usage"]["output_tokens"] == 4
        filtered = await store.report_business_events(start=start, end=end, agent_id="agent_test", max_events=1)
        assert tuple(filtered.runs) == ((handle.session_id, handle.run_id),)
        assert filtered.events_truncated
        capped = await store.report_business_events(start=start, end=end, max_runs=1)
        assert capped.cohort_truncated
        assert timing_report({}, {}, start=start, end=end, business=capped)["summary"]["coverage_rate"] is None

    if backend == "filesystem":
        async with open_filesystem(tmp_path) as store:
            handle = await exercise(store)
        async with open_filesystem(tmp_path) as store:
            await verify(store, handle)
    else:
        async with sql_store_factory(backend) as open_store:
            store = open_store()
            handle = await exercise(store)
            if backend.startswith("redis-"):
                now = utc_now().timestamp()
                pending = await store.report_business_events(start=now - 60, end=now + 60)
                assert not pending.archive_pending
                assert len(pending.runs) == 2
                assert pending.runs[handle.session_id, handle.run_id].usage_records == 1
                await store.archive_pending()
            await store.close()
            await verify(open_store(), handle)



async def test_remote_timing_failure_still_returns_business_summary(monkeypatch):
    import httpx

    from sagents.v2.runtime.observability.plugins.external.diagnostics import ExternalDiagnostics
    from sagents.v2.runtime.session.reporting import BusinessReplay, RunBusinessFacts
    from sagents.v2.runtime.session.run_metadata import RunMetadata

    now = utc_now()
    facts = RunBusinessFacts(RunMetadata("s", "r", now, RunState.COMPLETED, "agent"))
    business = BusinessReplay({("s", "r"): facts})
    diagnostics = ExternalDiagnostics(backend="phoenix", query_url="http://unused")

    async def offline(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(diagnostics, "_query", offline)
    try:
        options = dict(start=now.timestamp() - 60, end=now.timestamp() + 60)
        report = await diagnostics.report(**options, business=business)
        assert report["summary"]["requests"] == report["summary"]["completed"] == 1
        assert report["summary"]["coverage_rate"] is None
        assert report["timing_unavailable"]
        with pytest.raises(httpx.ConnectError):
            await diagnostics.report(**options)
    finally:
        await diagnostics.close()
