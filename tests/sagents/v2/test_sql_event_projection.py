from unittest.mock import AsyncMock

import pytest

from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore
from sagents.v2.runtime.session.plugins.mysql import _MysqlSessionState
from sagents.v2.runtime.session.plugins.postgres import _PostgresSessionState
from tests.sagents.v2.test_mysql_session_store_matrix import CONTEXT, command


@pytest.mark.asyncio
async def test_incremental_projection_skips_persisted_event_serialization():
    store = EphemeralSessionStore()
    created = await store.create_run(command(), CONTEXT)
    sid, rid = created.handle.session_id, created.handle.run_id
    full = store._dump_session_state_locked(sid)
    original = store._run_events[rid]

    class CountedEvent:
        calls = 0

        def model_dump(self, **kwargs):
            self.calls += 1
            return {"run_sequence": self.calls}

    counted = CountedEvent()
    # A long committed prefix must never be visited during append projection.
    store._run_events[rid] = [counted] * 10000
    projected = store._dump_session_state_locked(sid, event_offsets={rid: 9999})
    assert len(projected["run_events"][rid]) == counted.calls == 1
    assert (
        store._dump_session_state_locked(sid, event_offsets={rid: 10000})["run_events"][
            rid
        ]
        == []
    )
    assert counted.calls == 1
    reset = store._dump_session_state_locked(sid, event_offsets={rid: 10001})
    assert len(reset["run_events"][rid]) == 10000
    store._run_events[rid] = original
    assert store._dump_session_state_locked(sid) == full
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["mysql", "postgres"])
@pytest.mark.parametrize(
    "persisted,total,delta",
    [(10000, 10001, True), (10000, 10000, True), (10000, 1, True), (1, 2, False)],
)
async def test_sql_event_delta_counts_and_truncation(backend, persisted, total, delta):
    store = (
        _MysqlSessionState("mysql://user:password@localhost/test")
        if backend == "mysql"
        else _PostgresSessionState("postgresql://localhost/test")
    )
    store._persisted_run_sequences = {"run": persisted, "removed": 2}
    store._persisted_session_runs = {"session": {"run", "removed"}}
    start = persisted if delta and persisted <= total else 0
    rows = [{"run_sequence": n + 1} for n in range(start, total)]
    connection = AsyncMock()
    result = await store._persist_events(
        connection,
        "session",
        {"run": rows},
        **({"event_totals": {"run": total}} if delta else {}),
    )
    assert result == {"run": total}
    assert connection.execute.await_count == 1 + (persisted > total)
    expected = total if persisted > total else total - persisted
    if expected:
        inserted = connection.executemany.call_args.args[1]
        assert len(inserted) == expected
        assert inserted[-1][2] == total
    else:
        connection.executemany.assert_not_awaited()
    # Durable counters only advance after the surrounding transaction commits.
    assert store._persisted_run_sequences["run"] == persisted
