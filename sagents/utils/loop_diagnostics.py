"""A sleeping watchdog, active only while preparation/retrieval work is observed.

No asyncio debug mode, monkey-patching, locals, messages, or stack source text.
At most one pending heartbeat, one stack record/second, and bounded task maps.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
import gc
import os
from pathlib import Path
import sys
import threading
import time

_monitor = None


def current_monitor():
    return _monitor


def _stack(frame, limit=12):
    result = []
    while frame is not None and len(result) < limit:
        code = frame.f_code
        result.append(
            {
                "file": "/".join(code.co_filename.replace("\\", "/").split("/")[-2:]),
                "function": code.co_name,
                "line": frame.f_lineno,
            }
        )
        frame = frame.f_back
    return result


def _resources():
    result = {"process_cpu_seconds": round(time.process_time(), 3)}
    for name in (
        "cpu.stat",
        "cpu.max",
        "cpu.pressure",
        "io.pressure",
        "memory.events",
        "memory.current",
        "memory.max",
        "pids.current",
        "pids.max",
    ):
        try:
            result[name] = Path("/sys/fs/cgroup", name).read_text()[:1024].strip()
        except OSError:
            pass
    return result


class LoopDiagnostics:
    INTERVAL = 0.05
    STALL_SECONDS = 0.10
    RECORD_INTERVAL = 1.0
    MAX_OPERATIONS = 256
    MAX_JOBS = 1024

    def __init__(self, loop):
        self.loop = loop
        self.loop_thread = threading.get_ident()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.operations = {}
        self.jobs = {}
        self.gc_pauses = deque(maxlen=16)
        self.gc_started = None
        self.sequence = 0
        self.pending_heartbeat = None
        self.last_record = 0.0
        self.peak_pending = 0
        self.peak_running = 0
        self.dropped_jobs = 0
        self.thread = threading.Thread(
            target=self._run, name="sage-loop-diagnostics", daemon=True
        )

    def _gc_callback(self, phase, info):
        now = time.perf_counter()
        if phase == "start":
            self.gc_started = (now, threading.get_ident())
        elif phase == "stop" and self.gc_started is not None:
            started, thread_id = self.gc_started
            self.gc_started = None
            self.gc_pauses.append({
                "finished_at": now, "duration_ms": round((now - started) * 1000, 3),
                "generation": info.get("generation"), "thread_id": thread_id,
                "on_event_loop": thread_id == self.loop_thread,
                "collected": info.get("collected", 0),
            })

    def start(self):
        gc.callbacks.append(self._gc_callback)
        self.thread.start()

    def stop(self):
        if self._gc_callback in gc.callbacks:
            gc.callbacks.remove(self._gc_callback)
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=0.5)

    def enter(self, diagnostic):
        with self.lock:
            if len(self.operations) < self.MAX_OPERATIONS:
                self.operations[diagnostic.operation_id] = {
                    "operation_id": diagnostic.operation_id,
                    "operation": diagnostic.operation,
                    "session_id": diagnostic.session_id,
                }
            self.wake.set()

    def leave(self, diagnostic):
        with self.lock:
            self.operations.pop(diagnostic.operation_id, None)

    def submit(self, name):
        with self.lock:
            if len(self.jobs) >= self.MAX_JOBS:
                self.dropped_jobs += 1
                return None
            self.sequence += 1
            key = self.sequence
            self.jobs[key] = {
                "name": name,
                "submitted": time.perf_counter(),
                "thread": None,
            }
            pending = sum(job["thread"] is None for job in self.jobs.values())
            self.peak_pending = max(self.peak_pending, pending)
            self.wake.set()
            return key

    def started(self, key):
        with self.lock:
            if key in self.jobs:
                self.jobs[key]["thread"] = threading.get_ident()
                running = sum(job["thread"] is not None for job in self.jobs.values())
                self.peak_running = max(self.peak_running, running)

    def finished(self, key):
        with self.lock:
            self.jobs.pop(key, None)

    def snapshot(self):
        with self.lock:
            jobs = list(self.jobs.values())
            pending = [job for job in jobs if job["thread"] is None]
            return {
                "instrumented_jobs_only": True,
                "pending": len(pending),
                "running": len(jobs) - len(pending),
                "oldest_pending_ms": round(
                    (
                        time.perf_counter()
                        - min(
                            (job["submitted"] for job in pending),
                            default=time.perf_counter(),
                        )
                    )
                    * 1000,
                    3,
                ),
                "peak_pending_since_start": self.peak_pending,
                "peak_running_since_start": self.peak_running,
                "untracked_overflow": self.dropped_jobs,
                "top_pending": Counter(job["name"] for job in pending).most_common(5),
            }

    def _heartbeat(self):
        with self.lock:
            self.pending_heartbeat = None

    def _sample(self, now, sampler_gap):
        with self.lock:
            if not self.operations and not self.jobs:
                self.wake.clear()
                return
            if self.pending_heartbeat is None:
                self.pending_heartbeat = now
                self.loop.call_soon_threadsafe(self._heartbeat)
                return
            lag = now - self.pending_heartbeat
            if (
                lag < self.STALL_SECONDS
                or now - self.last_record < self.RECORD_INTERVAL
            ):
                return
            self.last_record = now
            operations = list(self.operations.values())[:8]
            workers = [
                (job["name"], job["thread"])
                for job in self.jobs.values()
                if job["thread"] is not None
            ][:4]
        seen = {ident for _, ident in workers}
        for thread in threading.enumerate():
            if len(workers) >= 4:
                break
            if thread.ident not in seen and thread.name.startswith(
                ("asyncio", "ThreadPoolExecutor", "session-context-io")
            ):
                workers.append(("untracked_executor_worker", thread.ident))
                seen.add(thread.ident)
        frames = sys._current_frames()
        loop_stack = _stack(frames.get(self.loop_thread))
        worker_stacks = [
            {"operation": name, "stack": _stack(frames.get(ident), 8)}
            for name, ident in workers
        ]
        del frames
        from sagents.utils.latency_diagnostics import _emit

        _emit(
            {
                "version": 1,
                "operation": "event_loop.stall",
                "timestamp": time.time(),
                "lag_ms": round(lag * 1000, 3),
                "sampler_gap_ms": round(sampler_gap * 1000, 3),
                "active_operations": operations,
                "pool": self.snapshot(),
                "event_loop_stack": loop_stack,
                "worker_stacks": worker_stacks,
                "resources": _resources(),
                "gc_pauses_recent": [p for p in list(self.gc_pauses) if time.perf_counter() - p["finished_at"] <= 2.0],
            }
        )

    def _run(self):
        while not self.stop_event.is_set():
            self.wake.wait()
            previous = time.perf_counter()
            while self.wake.is_set() and not self.stop_event.wait(self.INTERVAL):
                now = time.perf_counter()
                try:
                    self._sample(now, max(0.0, now - previous - self.INTERVAL))
                except Exception:
                    # Diagnostics must not interrupt serving or spin on errors.
                    pass
                previous = now


def start_loop_diagnostics():
    global _monitor
    if os.environ.get("SAGE_LATENCY_DIAGNOSTICS", "1") == "0":
        return
    if _monitor is None:
        _monitor = LoopDiagnostics(asyncio.get_running_loop())
        _monitor.start()


def stop_loop_diagnostics():
    global _monitor
    monitor, _monitor = _monitor, None
    if monitor is not None:
        monitor.stop()
