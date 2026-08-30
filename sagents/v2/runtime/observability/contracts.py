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

    async def fail_model_request(
        self, *, session_id: str, request: ModelRequest, error: Exception
    ) -> None: ...


class NoopDiagnosticSink:
    """Default sink used when a host does not opt into diagnostics."""

    async def begin_model_request(self, **kwargs: Any) -> None:
        return None

    async def complete_model_request(self, **kwargs: Any) -> None:
        return None

    async def fail_model_request(self, **kwargs: Any) -> None:
        return None


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


class NoopLogSink:
    format_version = "sage.log/v1"

    def write(self, record: LogRecord) -> None:
        del record

    def close(self) -> None:
        return None
