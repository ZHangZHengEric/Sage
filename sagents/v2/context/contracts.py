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
    reserve_input_tokens: int = Field(default=0, ge=0)
    max_messages: int | None = Field(default=None, gt=0)


class ContextRequestReservation(StrictModel):
    """Final-request space that is not part of the reducible conversation.

    Tool schemas and runtime-only suffix messages are selected by the Agent step
    builder, after canonical history has been assembled. Reserving their space
    lets reducers fit the conversation against the request that will actually be
    sent instead of only the message prefix they happen to receive.
    """

    tool_schema_tokens: int = Field(default=0, ge=0)
    hidden_tool_index_tokens: int = Field(default=0, ge=0)
    continuation_guidance_tokens: int = Field(default=0, ge=0)
    protocol_overhead_tokens: int = Field(default=0, ge=0)
    message_count: int = Field(default=0, ge=0)

    @property
    def input_tokens(self) -> int:
        """Total non-compressible input reserved outside the reducer."""

        return (
            self.tool_schema_tokens
            + self.hidden_tool_index_tokens
            + self.continuation_guidance_tokens
            + self.protocol_overhead_tokens
        )


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
    """Observe the exact request view without changing canonical history.

    ``source_messages`` is the append-only canonical ledger the projection was
    reduced from. Passing it here lets a derived index update incrementally at
    the one point where the ledger is already in memory, instead of every
    consumer rebuilding history from the SessionStore on each read.
    """

    async def observe_projection(
        self,
        run_id: str,
        projection: ContextProjection,
        *,
        session_id: str | None = None,
        source_messages: tuple[ModelMessage, ...] = (),
    ) -> None: ...


class ContextReductionScope(StrictModel):
    """Stable identity supplied to stateful context-reduction plugins."""

    context_key: Identifier
    session_id: Identifier
    run_id: Identifier
    source_sequence: int = Field(default=0, ge=0)
    response_language: str = "en"


class ContextReducer(Protocol):
    async def reduce(
        self,
        messages: tuple[ModelMessage, ...],
        budget: ContextBudget,
        *,
        scope: ContextReductionScope | None = None,
    ) -> ContextProjection: ...


class ContextUnitCompactor(Protocol):
    """Replace one indivisible unit without changing canonical Session facts."""

    async def compact(
        self, unit: tuple[ModelMessage, ...]
    ) -> tuple[ModelMessage, ...] | None: ...
