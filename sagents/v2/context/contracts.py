"""SAgents V2 module for context/contracts.py."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import Field

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.model.contracts import ModelMessage


class ContextStability(str, Enum):
    STABLE = "stable"
    SEMI_STABLE = "semi_stable"
    VOLATILE = "volatile"


class ContextPlacement(str, Enum):
    SYSTEM = "system"
    LATEST_USER = "latest_user"


class ContextSegment(StrictModel):
    segment_id: Identifier
    content: str
    stability: ContextStability
    placement: ContextPlacement = ContextPlacement.SYSTEM
    priority: int = 0
    sensitive: bool = False


class ContextSegmentProvider(Protocol):
    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]: ...


class ContextBudget(StrictModel):
    max_input_tokens: int = Field(gt=0)
    reserve_output_tokens: int = Field(default=0, ge=0)
    max_messages: int | None = Field(default=None, gt=0)


class ContextProjection(StrictModel):
    """The reducer-owned model request view and its searchable history boundary.

    ``historical_messages`` is authoritative: it contains canonical input
    messages that this reducer intentionally removed or replaced in
    ``messages``. Consumers must not infer history by diffing the two views.
    Reducer plugins that leave it empty explicitly expose no searchable
    history for this projection.
    """

    messages: tuple[ModelMessage, ...]
    historical_messages: tuple[ModelMessage, ...] = ()
    estimated_tokens: int = Field(ge=0)
    source_message_count: int = Field(ge=0)
    dropped_message_count: int = Field(default=0, ge=0)
    dropped_digest: str | None = None
    strategy: str = "none"


class ContextProjectionObserver(Protocol):
    """Observe the exact request view without changing canonical history."""

    async def observe_projection(
        self, run_id: str, projection: ContextProjection
    ) -> None: ...


class ContextReductionScope(StrictModel):
    """Stable identity supplied to stateful context-reduction plugins."""

    context_key: Identifier
    session_id: Identifier
    run_id: Identifier
    source_sequence: int = Field(default=0, ge=0)


class ContextReducer(Protocol):
    async def reduce(
        self,
        messages: tuple[ModelMessage, ...],
        budget: ContextBudget,
        *,
        scope: ContextReductionScope | None = None,
    ) -> ContextProjection: ...
