
from typing import Any, cast

from datetime import datetime, timezone
import sqlite3

import pytest

from sagents.v2.runtime.observability.performance import (
    build_run,
    summarize,
)
from sagents.v2.runtime.observability.plugins.sqlite.performance import (
    SCHEMA, project_log, project_model, report, backfill,
)
from tests.app.v2.server.test_file_downloads import identity
from tests.app.v2.server.test_admin import admin_login

BASE = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()


def event(
    at,
    name,
    *,
    identity=None,
    purpose=None,
    state=None,
    start=None,
    run="r",
    agent="agent",
):
    return dict(
        at=BASE + at,
        event=name,
        identity=identity,
        purpose=purpose,
        state=state,
        started_at=BASE + start if start is not None else None,
        run_id=run,
        session_id="s",
        agent_id=agent,
        turn_id=None,
    )


def model(start, end, *, identity="m", purpose="agent", first=3):
    return dict(
        run_id="r",
        request_id=identity,
        session_id="s",
        started_at=BASE + start,
        ended_at=BASE + end if end is not None else None,
        first_token_at=BASE + first,
        purpose=purpose,
        turn_id="t",
    )


def sample(*, outer=True):
    events = [
        event(2, "agent.run.started"),
        event(9, "agent.run.completed"),
        event(3, "tool.call.started", identity="tool"),
        event(8, "tool.call.completed", identity="tool"),
        event(4, "model.first_text", identity="m", purpose="agent"),
    ]
    if outer:
        events += [
            event(2, "server.run.performance.accepted", start=0),
            event(10, "server.run.performance.finished", state="completed"),
        ]
    return events, [model(2, 6)]


def test_initialization_cleanup_parallelism_and_first_token_are_included():
    events, models = sample()
    row = build_run(events, models)
    assert (
        row["total_ms"] == 10000
    )  # includes 2s of per-request initialization and 1s cleanup
    assert row["first_token_ms"] == 3000
    assert row["model_ttft_ms"] == 1000
    assert row["first_text_ms"] == 4000
    assert row["model_ms"] == 4000 and row["tool_ms"] == 5000
    assert row["overlap_ms"] == 3000
    assert row["framework_ms"] == 4000  # 10 - union([2,6], [3,8])
    assert row["coverage"] == "complete"
    assert summarize([row])["framework_ratio"] == 0.4


@pytest.mark.parametrize("incomplete", [False, True])
def test_in_memory_timings_match_exported_projection(incomplete):
    import json
    from sagents.v2.runtime.observability.performance.aggregation import normalize_timing_rows
    from sagents.v2.runtime.observability.performance.trace_projection import timing_rows

    events, models = sample()
    rows = [{"kind": "model", "at": BASE + 6, "data": {
        **models[0], "completed_at": datetime.fromtimestamp(cast('float', models[0]["ended_at"]), timezone.utc),
    }}]
    for value in events:
        rows.append({"kind": "log", "at": value["at"], "data": {
            "session_id": value["session_id"], "run_id": value["run_id"],
            "timestamp": datetime.fromtimestamp(cast('float', value["at"]), timezone.utc),
            "event": value["event"], "request_id": value["identity"],
            "tool_call_id": value["identity"], "attributes": {
                "agent_id": value["agent_id"], "purpose": value["purpose"],
                "started_at": value["started_at"], "run_state": value["state"],
            },
        }})
    remote_events, remote_models = timing_rows([{
        "name": "agent.run", "start_time": BASE,
        "context": {"trace_id": "trace", "span_id": "span"},
        "attributes": {"sage.performance.format": "events/v3",
                       "sage.performance.incomplete": incomplete,
                       "sage.performance.data": json.dumps(rows, default=str)},
    }])
    local_events, local_models = normalize_timing_rows(rows, incomplete=incomplete)
    local = build_run(local_events["r"], local_models["r"])
    assert local is not None
    assert local == build_run(remote_events["r"], remote_models["r"])
    assert (local["framework_ms"] is None) is incomplete


@pytest.mark.parametrize("missing", ["model_end", "tool_end", "outer", "missing_model"])
def test_missing_capture_is_never_mislabelled_as_framework_time(missing):
    events, models = sample(outer=missing != "outer")
    if missing == "model_end":
        models[0]["ended_at"] = None
    if missing == "tool_end":
        events = [e for e in events if e["event"] != "tool.call.completed"]
    if missing == "missing_model":
        events.append(event(6, "model.request.started", identity="not-captured"))
    row = build_run(events, models)
    assert row["framework_ms"] is None
    summary = summarize([row])
    assert summary["measured"] == 0
    assert cast('dict[str, Any]', summary["framework_ms"])["p50"] is None
    if missing == "outer":
        assert cast('dict[str, Any]', summary["first_token_ms"])["p50"] is None


def test_resumed_execution_excludes_human_wait_and_tracks_active_first_token():
    events = [
        event(0, "agent.run.started"),
        event(2, "agent.run.suspended"),
        event(1, "server.run.performance.accepted", start=0),
        event(100, "agent.run.started"),
        event(99, "server.run.performance.resuming", start=99),
        event(104, "agent.run.completed"),
        event(105, "server.run.performance.finished", state="completed"),
    ]
    row = build_run(events, [model(100, 103, first=101)])
    assert row["total_ms"] == 8000
    assert row["waiting_ms"] == 97000
    assert row["first_token_ms"] == 4000
    assert row["framework_ms"] == 5000


def test_auxiliary_llms_are_counted_but_not_user_first_text():
    events, models = sample()
    events.append(
        event(1, "model.first_text", purpose="conversation_summary", identity="summary")
    )
    models.append(
        model(0, 2, identity="summary", purpose="conversation_summary", first=cast('int', 0.5))
    )
    row = build_run(events, models)
    assert row["model_ms"] == 6000
    assert row["first_text_ms"] == 4000
    assert row["first_token_ms"] == 3000
    assert row["purposes"]["conversation_summary"] == {"calls": 1, "ms": 2000}


def insert_sample(db, *, run="r", agent="agent", shift=0):
    events, models = sample()
    for e in events:
        project_log(
            db,
            dict(
                event=e["event"],
                session_id="s",
                run_id=run,
                timestamp=cast('float', e["at"]) + cast('float', shift),
                tool_call_id=e["identity"] if cast('str', e["event"]).startswith("tool.") else None,
                request_id=e["identity"],
                attributes={
                    "agent_id": agent,
                    "purpose": e["purpose"],
                    "run_state": e["state"],
                    "started_at": cast('float', e["started_at"]) + cast('float', shift) if e["started_at"] else None,
                    "password": "MUST NOT BE STORED",
                    "arguments": {"private": "MUST NOT BE STORED"},
                },
            ),
        )
    for m in models:
        project_model(
            db,
            dict(
                run_id=run,
                request_id=m["request_id"],
                session_id="s",
                started_at=cast('float', m["started_at"]) + cast('float', shift),
                completed_at=cast('float', m["ended_at"]) + cast('float', shift),
                first_token_at=cast('float', m["first_token_at"]) + cast('float', shift),
                purpose=m["purpose"],
            ),
        )


def test_indexed_report_agent_time_and_timezone_buckets_without_payload_reads(tmp_path):
    path = tmp_path / "perf.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        insert_sample(db)
        insert_sample(db, run="other", agent="other", shift=3600)
        insert_sample(db, run="old", shift=-86400)
    result = report(path, start=BASE, end=BASE + 7200, agent_id="agent")
    assert result["summary"]["requests"] == 1
    assert result["summary"]["measured"] == 1
    assert result["buckets"][0]["time"] == "2026-10-19T08:00:00+08:00"
    assert result["buckets"][1]["requests"] == 0  # a gap is not a zero-latency sample
    bounded = report(path, start=BASE, end=BASE + 7200, max_runs=1)
    assert bounded["truncated"] is True
    assert bounded["runs"][0]["run_id"] == "other"
    scoped = report(path, start=BASE, end=BASE + 7200, agent_id="agent", max_runs=1)
    assert scoped["runs"][0]["run_id"] == "r"
    assert (
        report(path, start=BASE, end=BASE + 7200, max_timing_rows=1)["truncated"]
        is True
    )
    with sqlite3.connect(path) as db:
        assert "MUST NOT BE STORED" not in str(
            db.execute("SELECT * FROM performance_events").fetchall()
        )


def test_backfill_is_idempotent_and_preserves_partial_history(tmp_path):
    import json

    path = tmp_path / "evidence.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE logs(payload TEXT); CREATE TABLE models(session_id TEXT,run_id TEXT,request_id TEXT,payload TEXT); ALTER TABLE logs ADD session_id TEXT; ALTER TABLE logs ADD run_id TEXT;"
        )
        for e in [event(0, "agent.run.started"), event(10, "agent.run.completed")]:
            payload = {
                "event": e["event"],
                "timestamp": datetime.fromtimestamp(cast('float', e["at"]), timezone.utc).isoformat(),
                "attributes": {"agent_id": "agent", "password": "secret"},
            }
            db.execute(
                "INSERT INTO logs VALUES(?,?,?)", (json.dumps(payload), "s", "r")
            )
        db.execute(
            "INSERT INTO models VALUES(?,?,?,?)",
            (
                "s",
                "r",
                "m",
                json.dumps(
                    {
                        "started_at": datetime.fromtimestamp(
                            BASE + 2, timezone.utc
                        ).isoformat(),
                        "completed_at": datetime.fromtimestamp(
                            BASE + 6, timezone.utc
                        ).isoformat(),
                        "purpose": "agent",
                    }
                ),
            ),
        )
    assert backfill(path) == {"events": 2, "models": 1}
    backfill(path)
    result = report(path, start=BASE, end=BASE + 3600)
    assert result["summary"]["requests"] == 1
    assert result["summary"]["measured"] == 0
    assert result["runs"][0]["scope"] == "execution_only"


def test_performance_api_requires_admin_and_bounds_queries(client, service):
    user, _ = identity(client, "alice")
    assert client.get("/api/observability/performance", headers=user).status_code == 403
    admin = {"Authorization": f"Bearer {admin_login(client)}"}
    with sqlite3.connect(service.diagnostics.path) as db:
        insert_sample(db)
    params = {"start": "2026-10-19T00:00:00Z", "end": "2026-10-20T00:00:00Z"}
    response = client.get(
        "/api/observability/performance", params=params, headers=admin
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"]["framework_ms"]["p50"] == 4000
    for invalid in (
        {"start": "2026-01-01T00:00:00Z"},
        {"start": "2026-10-19T00:00:00"},
        {"timezone_name": "No/SuchZone"},
        {"bucket": "minute"},
        {"end": params["start"]},
    ):
        assert (
            client.get(
                "/api/observability/performance",
                params={**params, **invalid},
                headers=admin,
            ).status_code
            == 422
        )


def test_actual_sdk_request_includes_repeated_agent_loading(
    client, service, monkeypatch
):
    import asyncio
    from tests.app.v2.server.test_agui_chat import _run_input

    user, _ = identity(client, "timing-user")
    original = service.conversations.runs._load_run_agent
    original_admission = service.conversations.admission.prepare
    boundaries = {}

    async def slow_load(*args, **kwargs):
        await asyncio.sleep(0.05)  # repeated per-request initialization
        return await original(*args, **kwargs)

    async def slow_admission(*args, **kwargs):
        boundaries["admission"] = datetime.now(timezone.utc).timestamp()
        await asyncio.sleep(0.05)
        return await original_admission(*args, **kwargs)

    monkeypatch.setattr(service.conversations.runs, "_load_run_agent", slow_load)
    monkeypatch.setattr(service.conversations.admission, "prepare", slow_admission)
    response = client.post("/api/agent", json=_run_input(), headers=user)
    assert response.status_code == 200

    async def settle():
        async with asyncio.timeout(10):
            while service.execution._drives:
                await asyncio.sleep(0.01)

    client.portal.call(settle)
    service.diagnostics._flush()
    admin = {"Authorization": f"Bearer {admin_login(client)}"}
    metrics = client.get("/api/observability/performance", headers=admin).json()["data"]
    row = metrics["runs"][0]
    assert row["scope"] == "sdk_entry"
    assert (
        datetime.fromisoformat(row["started_at"]).timestamp() <= boundaries["admission"]
    )
    assert row["state"] == "completed"
    assert row["coverage"] == "complete"
    assert row["framework_ms"] >= 100
    assert row["first_token_ms"] >= 100
