"""Bounded wall-clock accounting for first output and non-model work.

Model time is the union of SDK create/stream-read awaits, not a sum of parallel
calls. Consumer processing between chunks remains outside model time.
"""

from __future__ import annotations

import contextvars
import functools
from contextlib import contextmanager
import time
import os
import uuid

from sagents.utils.latency_diagnostics import _emit

_current = contextvars.ContextVar("request_latency", default=None)


class RequestLatency:
    def __init__(self):
        self.started = time.perf_counter()
        self.operation_id = uuid.uuid4().hex[:16]
        self.session_id = ""
        self.active = 0
        self.model_started = None
        self.model_seconds = 0.0
        self.model_calls = 0
        self.tool_calls = 0
        self.tool_active = 0
        self.tool_started = None
        self.tool_seconds = 0.0
        self.external_active = 0
        self.external_started = None
        self.external_seconds = 0.0
        self.first_recorded = False
        self.finished = False
        self.stages = {}
        self.stream_stages = {}
        self.stream_gauges = {}
        self.stream_diagnostics = os.environ.get("SAGE_LATENCY_DIAGNOSTICS", "1") != "0"

    @contextmanager
    def activate(self):
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    def add_stage(self, name, seconds):
        if len(self.stages) < 16 or name in self.stages:
            count, total = self.stages.get(name, (0, 0.0))
            self.stages[name] = (count + 1, total + max(0.0, seconds))

    def add_stream_timing(self, name, seconds, cpu_seconds=None):
        # Fixed-size numeric aggregates; never retain a chunk or per-token log.
        if not self.stream_diagnostics or (name not in self.stream_stages and len(self.stream_stages) >= 24):
            return
        stat = self.stream_stages.setdefault(name, [0, 0.0, 0.0, 0.0, 0])
        elapsed = max(0.0, seconds)
        stat[0] += 1
        stat[1] += elapsed
        stat[2] = max(stat[2], elapsed)
        if cpu_seconds is not None:
            stat[3] += max(0.0, cpu_seconds)
            stat[4] += 1

    def stream_snapshot(self, prefix=""):
        return {
            name: {"count": value[0], "total_ms": round(value[1] * 1000, 3),
                   "max_ms": round(value[2] * 1000, 3),
                   "cpu_ms": round(value[3] * 1000, 3) if value[4] else None,
                   "cpu_count": value[4]}
            for name, value in self.stream_stages.items() if name.startswith(prefix)
        }

    def record_queue_depth(self, depth):
        if self.stream_diagnostics:
            self.stream_gauges["merge_queue_peak"] = max(depth, self.stream_gauges.get("merge_queue_peak", 0))

    def emit_delivery_summary(self):
        if self.stream_diagnostics:
            _emit({"version": 1, "operation": "request.stream_delivery",
                   "timestamp": time.time(), "operation_id": self.operation_id,
                   "session_id": str(self.session_id)[:128],
                   "stream_stages": self.stream_snapshot("delivery."),
                   "stream_gauges": dict(self.stream_gauges)})

    def external_enter(self):
        if self.external_active == 0:
            self.external_started = time.perf_counter()
        self.external_active += 1

    def external_leave(self):
        self.external_active -= 1
        if self.external_active == 0:
            self.external_seconds += max(
                0.0, time.perf_counter() - self.external_started
            )
            self.external_started = None

    def snapshot(self, operation):
        now = time.perf_counter()
        total = max(0.0, now - self.started)
        model = self.model_seconds
        if self.active and self.model_started is not None:
            model += max(0.0, now - self.model_started)
        model = min(total, model)
        tool = self.tool_seconds
        if self.tool_active and self.tool_started is not None:
            tool += max(0.0, now - self.tool_started)
        external = self.external_seconds
        if self.external_active and self.external_started is not None:
            external += max(0.0, now - self.external_started)
        external = min(total, external)
        local = max(0.0, total - external)
        return {
            "version": 1,
            "operation": operation,
            "timestamp": time.time(),
            "operation_id": self.operation_id,
            "session_id": str(self.session_id)[:128],
            "status": "slow" if local > 1 else "ok",
            "elapsed_ms": round(total * 1000, 3),
            "model_wait_union_ms": round(model * 1000, 3),
            "tool_execution_union_ms": round(tool * 1000, 3),
            "model_or_tool_union_ms": round(external * 1000, 3),
            "non_model_ms": round((total - model) * 1000, 3),
            "framework_overhead_ms": round(local * 1000, 3),
            "framework_target_ms": 1000,
            "stages": {
                k: {"count": v[0], "total_ms": round(v[1] * 1000, 3)}
                for k, v in self.stages.items()
            },
            "counts": {"model_calls": self.model_calls, "tool_calls": self.tool_calls},
            "slow_files": [],
            "stream_stages": self.stream_snapshot(),
            "stream_gauges": dict(self.stream_gauges),
        }

    def first_output(self):
        if not self.first_recorded and not self.finished:
            self.first_recorded = True
            if os.environ.get("SAGE_LATENCY_DIAGNOSTICS", "1") != "0":
                _emit(self.snapshot("request.first_output"))

    def finish(self):
        if self.finished:
            return
        payload = self.snapshot("request.completed")
        self.finished = True
        # Full-turn framework overhead is separate from time to first output.
        # Model waits and tool execution are both excluded from the 1 s target.
        payload["counts"]["first_output_recorded"] = int(self.first_recorded)
        if os.environ.get("SAGE_LATENCY_DIAGNOSTICS", "1") != "0":
            _emit(payload)


def record_first_output():
    budget = _current.get()
    if budget is not None:
        budget.first_output()


@contextmanager
def model_wait(*, new_call=False):
    budget = _current.get()
    if budget is None or budget.finished:
        yield
        return
    if new_call:
        budget.model_calls += 1
    if budget.active == 0:
        budget.model_started = time.perf_counter()
    budget.active += 1
    budget.external_enter()
    try:
        yield
    finally:
        budget.external_leave()
        budget.active -= 1
        if budget.active == 0:
            budget.model_seconds += max(0.0, time.perf_counter() - budget.model_started)
            budget.model_started = None


class TimedModelStream:
    def __init__(self, stream):
        self.stream = stream
        self.iterator = stream.__aiter__()
        self.last_returned_at = None

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.last_returned_at is not None:
            record_stage("model.stream_consumer", time.perf_counter() - self.last_returned_at)
            self.last_returned_at = None
        with model_wait():
            result = await self.iterator.__anext__()
        self.last_returned_at = time.perf_counter()
        return result

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)


def observe_stream(response, streaming):
    if streaming and _current.get() is not None and hasattr(response, "__aiter__"):
        return TimedModelStream(response)
    return response


def record_stage(name, seconds):
    budget = _current.get()
    if budget is not None:
        budget.add_stage(name, seconds)


@contextmanager
def tool_execution():
    budget = _current.get()
    if budget is None or budget.finished:
        yield
        return
    budget.tool_calls += 1
    if budget.tool_active == 0:
        budget.tool_started = time.perf_counter()
    budget.tool_active += 1
    budget.external_enter()
    try:
        yield
    finally:
        budget.external_leave()
        budget.tool_active -= 1
        if budget.tool_active == 0:
            budget.tool_seconds += max(0.0, time.perf_counter() - budget.tool_started)
            budget.tool_started = None


def timed_tool_execution(fn):
    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        with tool_execution():
            return await fn(*args, **kwargs)

    return wrapped


@contextmanager
def request_stage(name):
    budget = _current.get()
    if budget is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        budget.add_stage(name, time.perf_counter() - started)


def current_stream_budget():
    budget = _current.get()
    return budget if budget is not None and budget.stream_diagnostics and not budget.finished else None


def timed_stream_sync(name):
    """Measure only synchronous code: never apply to an async function/generator.

    Thread CPU excludes other event-loop tasks because this scope cannot await.
    Wall minus CPU may include GIL/OS scheduling or synchronous I/O, not just I/O.
    Nested scopes are inclusive and must not be summed.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            budget = current_stream_budget()
            if budget is None:
                return fn(*args, **kwargs)
            started, cpu = time.perf_counter(), time.thread_time()
            try:
                return fn(*args, **kwargs)
            finally:
                budget.add_stream_timing(name, time.perf_counter() - started, time.thread_time() - cpu)
        return wrapped
    return decorate


@contextmanager
def stream_sync_stage(name, budget=None):
    budget = budget or current_stream_budget()
    if budget is None or not budget.stream_diagnostics:
        yield
        return
    started, cpu = time.perf_counter(), time.thread_time()
    try:
        yield
    finally:
        budget.add_stream_timing(name, time.perf_counter() - started, time.thread_time() - cpu)
