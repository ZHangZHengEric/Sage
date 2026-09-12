import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time
from types import SimpleNamespace

from sagents.utils import latency_diagnostics as d


def test_thread_queue_execution_and_event_loop_resume_are_separate(monkeypatch):
    records = []
    monkeypatch.setattr(d, "_emit", records.append)
    monkeypatch.setenv("SAGE_LATENCY_DIAGNOSTICS", "1")

    @d.diagnose("test", 0)
    async def operation(session_id):
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        gate = threading.Event()
        blocker = executor.submit(gate.wait, 1)
        loop.call_later(0.035, gate.set)
        finished = threading.Event()

        def work():
            time.sleep(0.015)
            finished.set()
            return 17

        task = asyncio.create_task(d.to_thread("work", work))
        # Block the event loop only in this test, after work has been submitted.
        await asyncio.sleep(0.04)
        finished.wait(1)
        time.sleep(0.035)
        assert await task == 17
        blocker.result(1)

    asyncio.run(operation("test-session"))
    stages = records[0]["stages"]
    assert stages["work.queue"]["max_ms"] >= 20
    assert stages["work.run"]["max_ms"] >= 10
    assert stages["work.resume"]["max_ms"] >= 25
    assert stages["work.cpu"]["max_ms"] < stages["work.run"]["max_ms"]
    assert records[0]["session_id"] == "test-session"
    assert d._current.get() is None


def test_fast_operations_are_silent_and_scopes_do_not_mix(monkeypatch):
    records = []
    monkeypatch.setattr(d, "_emit", records.append)
    monkeypatch.setenv("SAGE_LATENCY_DIAGNOSTICS", "1")

    @d.diagnose("fast", 100000)
    async def fast():
        d.count("fast")

    @d.diagnose("slow", 0)
    async def slow(session_id):
        d.count(session_id)
        await asyncio.sleep(0)

    async def run():
        await fast()
        await asyncio.gather(slow("a"), slow("b"))

    asyncio.run(run())
    assert len(records) == 2
    assert {r["session_id"] for r in records} == {"a", "b"}
    assert all(r["counts"] == {r["session_id"]: 1} for r in records)


def test_lock_wait_cancellation_does_not_release_someone_elses_lock(monkeypatch):
    records = []
    monkeypatch.setattr(d, "_emit", records.append)

    @d.diagnose("cancel", 100000)
    async def waiter(lock):
        async with d.timed_lock("scope", lock):
            raise AssertionError("must not acquire")

    async def run():
        lock = asyncio.Lock()
        await lock.acquire()
        task = asyncio.create_task(waiter(lock))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert lock.locked()
        lock.release()

    asyncio.run(run())
    assert records[0]["status"] == "cancelled"
    assert "scope.wait" in records[0]["stages"]


def test_cardinality_and_file_details_are_bounded_and_private():
    diagnostic = d.Diagnostic("test")
    for i in range(200):
        diagnostic.add(str(i), 0.1)
        diagnostic.count(str(i))
        diagnostic.file(
            SimpleNamespace(path=f"/private/secret{i}.txt", size=i), i / 100
        )
    record = diagnostic.snapshot("ok")
    assert len(record["stages"]) == 96
    assert len(record["counts"]) == 64
    assert len(record["slow_files"]) == 5
    assert "secret" not in json.dumps(record)
    assert record["slow_files"][0]["size_bytes"] == 199


def test_log_size_and_three_day_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_LOGS_DIR_PATH", str(tmp_path))
    monkeypatch.setattr(d, "_sink", None)
    stale = tmp_path / "latency-diagnostics.jsonl.2020-01-01"
    stale.write_text("old")
    os.utime(stale, (1, 1))
    d._emit({"test": 1})
    assert not stale.exists()
    handler = d._sink.handlers[0]
    assert handler.backupCount == 2
    assert handler.utc is True
    handler.stream.close()
    handler.stream = None
    path = tmp_path / "latency-diagnostics.jsonl"
    with path.open("r+b") as stream:
        stream.truncate(10 * 1024 * 1024)
    d._emit({"test": 2})
    assert path.stat().st_size == 10 * 1024 * 1024
    # Daily rollover still runs when the previous day reached its cap.
    handler.rolloverAt = time.time() - 1
    d._emit({"test": 3})
    assert json.loads(path.read_text()) == {"test": 3}
    handler.close()


def test_nested_preparation_shares_one_summary_and_reports_partial_errors(monkeypatch):
    records = []
    monkeypatch.setattr(d, "_emit", records.append)

    @d.diagnose("prepare", 100000)
    async def inner():
        d.count("index.read_errors")

    @d.diagnose("prepare", 100000)
    async def outer(session_id):
        await inner()

    asyncio.run(outer("nested"))
    assert len(records) == 1
    assert records[0]["session_id"] == "nested"
    assert records[0]["status"] == "partial_error"
    assert records[0]["stages"]["prepare.nested"]["count"] == 1
