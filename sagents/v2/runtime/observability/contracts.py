"""Optional observability ports that never participate in Session recovery."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import Field

from sagents.v2.contracts.common import StrictModel, utc_now

if TYPE_CHECKING:
    from sagents.v2.model.contracts import ModelRequest, ModelResponse


class DiagnosticSink(Protocol):
    """Record model diagnostics independently from authoritative Session data."""

    async def begin_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        provider: Mapping[str, Any],
        wire_request: Mapping[str, Any] | None = None,
    ) -> None: ...

    async def complete_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        response: ModelResponse,
    ) -> None: ...

    async def record_model_first_token(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        observed_at: datetime,
    ) -> None: ...

    async def fail_model_request(
        self, *, session_id: str, request: ModelRequest, error: Exception
    ) -> None: ...


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogError(StrictModel):
    type: str
    message: str
    code: str | None = None
    category: str | None = None
    stack_trace: str | None = None


class LogRecord(StrictModel):
    """Stable structured record shared by hosts, Runtime, Agent, and plugins."""

    format_version: str = "sage.log/v1"
    timestamp: datetime = Field(default_factory=utc_now)
    level: LogLevel
    event: str
    message: str
    component: str
    logger: str | None = None
    process_id: int | None = None
    session_id: str | None = None
    run_id: str | None = None
    turn_id: str | None = None
    step_id: str | None = None
    tool_call_id: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    error: LogError | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class LogSink(Protocol):
    """Replaceable best-effort projection for structured operational logs."""

    format_version: str

    def write(self, record: LogRecord) -> None: ...

    def close(self) -> None: ...


class TraceStatus(str, Enum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class TraceKind(str, Enum):
    INTERNAL = "internal"
    CLIENT = "client"
    SERVER = "server"


class TraceEvent(StrictModel):
    name: str
    timestamp: datetime = Field(default_factory=utc_now)
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceSpan(StrictModel):
    """Vendor-neutral span shared by Runtime, hosts, and export plugins."""

    format_version: str = "sage.trace/v1"
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: TraceKind = TraceKind.INTERNAL
    start_time: datetime = Field(default_factory=utc_now)
    end_time: datetime | None = None
    status: TraceStatus = TraceStatus.UNSET
    session_id: str | None = None
    run_id: str | None = None
    turn_id: str | None = None
    step_id: str | None = None
    tool_call_id: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[TraceEvent] = Field(default_factory=list)
    error: LogError | None = None


class TraceSink(Protocol):
    """Replaceable best-effort projection for distributed traces."""

    format_version: str

    def start_span(self, span: TraceSpan) -> None: ...

    def add_event(self, span_id: str, event: TraceEvent) -> None: ...

    def end_span(self, span: TraceSpan) -> None: ...

    def close(self) -> None: ...
