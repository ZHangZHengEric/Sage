"""Explicit projection contract from canonical RuntimeEvents to wire protocols."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.events import RuntimeEvent


class MappingFidelity(str, Enum):
    EXACT = "exact"
    EXTENSION = "extension"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


class AdapterCapabilities(StrictModel):
    protocol: Identifier
    protocol_version: str
    adapter_version: str
    supports_run_lifecycle: bool
    supports_item_lifecycle: bool
    supports_reasoning: bool
    supports_tool_lifecycle: bool
    supports_interactions: bool
    supports_pause_resume: bool
    supports_exact_cursor_replay: bool
    supports_flow: bool
    supports_artifacts: bool
    extensions: tuple[Identifier, ...] = ()


class ProtocolFrame(StrictModel):
    protocol: Identifier
    protocol_version: str
    frame_kind: Literal["event", "request", "response", "notification"]
    name: str
    frame_id: Identifier | None = None
    payload: dict[str, Any]
    source_event_id: Identifier
    source_run_sequence: int = Field(ge=1)


class LossReport(StrictModel):
    source_event_id: Identifier
    source_event_type: str
    fidelity: MappingFidelity
    code: Identifier
    detail: str
    preserved_by_extension: bool = False


class AdapterResult(StrictModel):
    """Frames plus an auditable account of every semantic downgrade."""

    frames: tuple[ProtocolFrame, ...] = ()
    losses: tuple[LossReport, ...] = ()

    @model_validator(mode="after")
    def reject_silent_drop(self) -> "AdapterResult":
        # Every Native event must be represented or explicitly reported as lost.
        # This prevents a protocol from appearing compatible while silently
        # discarding approval, pause, Flow, or durability semantics.
        if not self.frames and not self.losses:
            raise ValueError("adapter result cannot silently drop an event")
        return self


class ProtocolAdapter(Protocol):
    """One-way projection; adapters never become the canonical Run model."""

    async def capabilities(self) -> AdapterCapabilities: ...
    def translate(self, event: RuntimeEvent) -> AdapterResult: ...


def frame(
    event: RuntimeEvent,
    *,
    protocol: str,
    version: str,
    name: str,
    payload: dict[str, Any],
    frame_kind: str = "event",
    frame_id: str | None = None,
) -> ProtocolFrame:
    return ProtocolFrame(
        protocol=protocol,
        protocol_version=version,
        frame_kind=frame_kind,
        name=name,
        frame_id=frame_id,
        payload=payload,
        source_event_id=event.event_id,
        source_run_sequence=event.run_sequence,
    )


def loss(
    event: RuntimeEvent,
    *,
    fidelity: MappingFidelity,
    code: str,
    detail: str,
    preserved_by_extension: bool = False,
) -> LossReport:
    return LossReport(
        source_event_id=event.event_id,
        source_event_type=event.type,
        fidelity=fidelity,
        code=code,
        detail=detail,
        preserved_by_extension=preserved_by_extension,
    )
