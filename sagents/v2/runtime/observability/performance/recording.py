"""Content-free timing facts emitted at execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RunTimingStage:
    session_id: str
    run_id: str
    event: str
    segment: str
    at: datetime
    identity: str | None = None
    agent_id: str | None = None
    purpose: str | None = None
    started_at: datetime | None = None
    turn_id: str | None = None
    state: str | None = None


@dataclass(frozen=True, slots=True)
class ModelTiming:
    session_id: str
    run_id: str
    request_id: str
    purpose: str
    turn_id: str | None
    started_at: datetime
    first_token_at: datetime | None = None
    first_text_at: datetime | None = None
    ended_at: datetime | None = None


class PerformanceSink(Protocol):
    def record_stage(self, stage: RunTimingStage) -> None: ...
    def record_model(self, timing: ModelTiming) -> None: ...


class PerformanceRecorder:
    """Pass timings to a host sink without letting telemetry fail a Run."""

    def __init__(self, sink: PerformanceSink | None = None) -> None:
        self.sink = sink
        self.trace_sink: PerformanceSink | None = None
        self.failures = 0

    @property
    def enabled(self) -> bool:
        return self.sink is not None or self.trace_sink is not None

    def record_stage(self, stage: RunTimingStage) -> None:
        for sink in (self.sink, self.trace_sink):
            if sink is not None:
                try:
                    sink.record_stage(stage)
                except Exception:
                    self.failures += 1

    def record_model(self, timing: ModelTiming) -> None:
        for sink in (self.sink, self.trace_sink):
            if sink is not None:
                try:
                    sink.record_model(timing)
                except Exception:
                    self.failures += 1
