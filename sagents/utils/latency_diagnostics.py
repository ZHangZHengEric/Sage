"""Bounded request timings with optional active-operation loop diagnostics."""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import hashlib
import uuid
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from sagents.utils.loop_diagnostics import current_monitor

_current = contextvars.ContextVar("latency_diagnostic", default=None)
_log_lock = threading.Lock()
_sink = None


class _CappedDailyHandler(TimedRotatingFileHandler):
    """Current UTC day plus two backups, at most 10 MiB per day."""

    def getFilesToDelete(self):
        expired = set(super().getFilesToDelete())
        oldest_day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 2 * 86400))
        base = Path(self.baseFilename)
        for path in base.parent.glob(base.name + ".????-??-??"):
            if path.name[-10:] < oldest_day:
                expired.add(str(path))
        return sorted(expired)

    def emit(self, record):
        try:
            if self.shouldRollover(record):
                self.doRollover()
            if self.stream is None:
                self.stream = self._open()
            # Reserve enough room for one bounded record and a saturation marker.
            if self.stream.tell() >= 10 * 1024 * 1024 - 32768:
                return
            super().emit(record)
        except Exception:
            # Telemetry must never fail a user operation or disclose its payload.
            pass


def _emit(payload):
    global _sink
    try:
        with _log_lock:
            if _sink is None:
                root = Path(os.environ.get("SAGE_LOGS_DIR_PATH", "logs"))
                root.mkdir(parents=True, exist_ok=True)
                handler = _CappedDailyHandler(
                    root / "latency-diagnostics.jsonl",
                    when="midnight",
                    backupCount=2,
                    utc=True,
                    encoding="utf-8",
                    delay=True,
                )
                # Remove expired backups on first write after a long idle/restart.
                for path in handler.getFilesToDelete():
                    Path(path).unlink(missing_ok=True)
                _sink = logging.Logger("sage.latency.diagnostics", logging.INFO)
                _sink.propagate = False
                _sink.addHandler(handler)
            _sink.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    except Exception:
        pass


class Diagnostic:
    def __init__(self, operation, session_id=None):
        self.operation = operation
        self.session_id = str(session_id or "")[:128]
        self.started = time.perf_counter()
        self.operation_id = uuid.uuid4().hex[:16]
        self.slow_files = []
        self.stages = {}
        self.counters = {}
        self.lock = threading.Lock()

    def add(self, name, seconds):
        with self.lock:
            if name not in self.stages and len(self.stages) >= 96:
                return
            item = self.stages.setdefault(name, [0, 0.0, 0.0])
            item[0] += 1
            item[1] += seconds * 1000
            item[2] = max(item[2], seconds * 1000)

    def count(self, name, value=1):
        with self.lock:
            if name in self.counters or len(self.counters) < 64:
                self.counters[name] = self.counters.get(name, 0) + value

    def file(self, entry, seconds):
        if seconds < 0.05:
            return
        with self.lock:
            elapsed = round(seconds * 1000, 3)
            if (
                len(self.slow_files) == 5
                and elapsed <= self.slow_files[-1]["elapsed_ms"]
            ):
                return
            self.slow_files.append(
                {
                    "path_hash": hashlib.sha256(entry.path.encode()).hexdigest()[:16],
                    "size_bytes": entry.size or 0,
                    "elapsed_ms": elapsed,
                }
            )
            self.slow_files.sort(key=lambda item: item["elapsed_ms"], reverse=True)
            del self.slow_files[5:]

    def snapshot(self, status):
        with self.lock:
            return {
                "version": 1,
                "timestamp": time.time(),
                "operation": self.operation,
                "session_id": self.session_id,
                "operation_id": self.operation_id,
                "status": status,
                "elapsed_ms": round((time.perf_counter() - self.started) * 1000, 3),
                "stages": {
                    k: {
                        "count": v[0],
                        "total_ms": round(v[1], 3),
                        "max_ms": round(v[2], 3),
                    }
                    for k, v in self.stages.items()
                },
                "counts": dict(self.counters),
                "slow_files": list(self.slow_files),
            }


def count(name, value=1):
    diagnostic = _current.get()
    if diagnostic is not None:
        diagnostic.count(name, value)


@contextmanager
def stage(name):
    diagnostic = _current.get()
    if diagnostic is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        diagnostic.add(name, time.perf_counter() - started)


def timed(name):
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def asynchronous(*args, **kwargs):
                with stage(name):
                    return await fn(*args, **kwargs)

            return asynchronous

        @functools.wraps(fn)
        def synchronous(*args, **kwargs):
            diagnostic = _current.get()
            if diagnostic is None:
                return fn(*args, **kwargs)
            cpu = time.thread_time()
            try:
                with stage(name):
                    return fn(*args, **kwargs)
            finally:
                diagnostic.add(name + ".cpu", time.thread_time() - cpu)

        return synchronous

    return decorate


@asynccontextmanager
async def timed_lock(name, lock):
    with stage(name + ".wait"):
        await lock.acquire()
    try:
        with stage(name + ".hold"):
            yield
    finally:
        lock.release()


async def to_thread(name, fn, /, *args, **kwargs):
    diagnostic = _current.get()
    if diagnostic is None:
        return await asyncio.to_thread(fn, *args, **kwargs)
    submitted = time.perf_counter()
    completed = None
    monitor = current_monitor()
    job = monitor.submit(name) if monitor is not None else None
    has_started = threading.Event()

    def run():
        nonlocal completed
        has_started.set()
        if monitor is not None:
            monitor.started(job)
        started = time.perf_counter()
        cpu = time.thread_time()
        diagnostic.add(name + ".queue", started - submitted)
        try:
            return fn(*args, **kwargs)
        finally:
            completed = time.perf_counter()
            diagnostic.add(name + ".run", completed - started)
            diagnostic.add(name + ".cpu", time.thread_time() - cpu)
            if monitor is not None:
                monitor.finished(job)

    try:
        return await asyncio.to_thread(run)
    finally:
        if monitor is not None and not has_started.is_set():
            monitor.finished(job)
        if completed is not None:
            diagnostic.add(name + ".resume", time.perf_counter() - completed)
        else:
            diagnostic.count("thread_cancelled_before_completion")


def diagnose(operation, threshold_ms):
    """Separate operation scopes: only slow/error operations emit a single summary."""

    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            if os.environ.get("SAGE_LATENCY_DIAGNOSTICS", "1") == "0":
                return await fn(*args, **kwargs)
            parent = _current.get()
            if parent is not None and parent.operation == operation:
                with stage(operation + ".nested"):
                    return await fn(*args, **kwargs)
            bound = signature.bind_partial(*args, **kwargs)
            session_id = bound.arguments.get("session_id")
            if session_id is None:
                session_id = getattr(bound.arguments.get("self"), "session_id", None)
            if session_id is None:
                session_id = getattr(bound.arguments.get("request"), "session_id", None)
            diagnostic = Diagnostic(operation, session_id)
            token = _current.set(diagnostic)
            monitor = current_monitor()
            if monitor is not None:
                monitor.enter(diagnostic)
            status = "ok"
            try:
                return await fn(*args, **kwargs)
            except BaseException as exc:
                status = (
                    "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
                )
                raise
            finally:
                _current.reset(token)
                if monitor is not None:
                    monitor.leave(diagnostic)
                elapsed = (time.perf_counter() - diagnostic.started) * 1000
                if operation in {"session.prepare", "memory.search", "prompt_budget.manifest"}:
                    from sagents.utils.request_latency import record_stage
                    record_stage(operation, elapsed / 1000)
                with diagnostic.lock:
                    has_errors = any(
                        key.endswith("errors") and value
                        for key, value in diagnostic.counters.items()
                    )
                if status == "ok" and has_errors:
                    status = "partial_error"
                if elapsed >= threshold_ms or status != "ok":
                    payload = diagnostic.snapshot(status)
                    if monitor is not None:
                        payload["pool_at_completion"] = monitor.snapshot()
                    _emit(payload)

        return wrapped

    return decorate


def timed_file(fn):
    @functools.wraps(fn)
    async def wrapped(self, entry, *args, **kwargs):
        diagnostic = _current.get()
        if diagnostic is None:
            return await fn(self, entry, *args, **kwargs)
        started = time.perf_counter()
        try:
            return await fn(self, entry, *args, **kwargs)
        finally:
            diagnostic.file(entry, time.perf_counter() - started)

    return wrapped


def record_first_output_latency(session_id, latency_ms):
    """Flag Sage-side first output above 3 s; this is not a request timeout."""
    if latency_ms <= 3000 or os.environ.get("SAGE_LATENCY_DIAGNOSTICS", "1") == "0":
        return
    _emit(
        {
            "version": 1,
            "operation": "first_output.slow",
            "timestamp": time.time(),
            "session_id": str(session_id or "")[:128],
            "operation_id": uuid.uuid4().hex[:16],
            "status": "slow",
            "elapsed_ms": latency_ms,
            "target_ms": 3000,
            "stages": {},
            "counts": {},
            "slow_files": [],
        }
    )
