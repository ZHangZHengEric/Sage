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
    """Provide context from the command, optionally from the current ledger.

    Providers may also expose ``segments_for_ledger(command, ledger, *, run_id)``.
    The default assembler uses that hook for history and applied steering input.
    """

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]: ...


class ContextBudget(StrictModel):
    max_input_tokens: int = Field(gt=0)
    reserve_output_tokens: int = Field(default=0, ge=0)
    reserve_input_tokens: int = Field(default=0, ge=0)
    max_messages: int | None = Field(default=None, gt=0)
    # Legacy manifest fields, retained for deserialization only. No estimation.
    max_system_tokens: int = Field(default=16_384, gt=0)
    # Legacy manifest field; history protection uses complete conversation units.
    protected_recent_tokens: int = Field(default=8_192, ge=0)


class ContextRequestReservation(StrictModel):
    """Legacy request reservation, accepted for source compatibility only."""

    tool_schema_tokens: int = Field(default=0, ge=0)
    hidden_tool_index_tokens: int = Field(default=0, ge=0)
    continuation_guidance_tokens: int = Field(default=0, ge=0)
    protocol_overhead_tokens: int = Field(default=0, ge=0)
    runtime_context_tokens: int = Field(default=0, ge=0)
    message_count: int = Field(default=0, ge=0)

    @property
    def input_tokens(self) -> int:
        """Total non-compressible input reserved outside the reducer."""

        return (
            self.tool_schema_tokens
            + self.hidden_tool_index_tokens
            + self.continuation_guidance_tokens
            + self.protocol_overhead_tokens
            + self.runtime_context_tokens
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
    estimated_tokens: int = Field(default=0, ge=0)  # legacy persisted snapshots only
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

    force: bool = False
    allow_reference_compaction: bool = True
    # Only an actual rejected request justifies rewriting a checkpoint without
    # advancing history coverage. Advisory usage pressure should reuse it.
    allow_summary_rewrite: bool = True
    context_key: Identifier
    session_id: Identifier
    run_id: Identifier
    source_sequence: int = Field(default=0, ge=0)
    response_language: str = "en"
    # The reducer receives a filtered history view. Persistent coverage still
    # hashes the canonical ledger, using these payload-to-ledger positions.
    canonical_messages: tuple[ModelMessage, ...] | None = None
    canonical_indices: tuple[int, ...] = ()


class ContextReducer(Protocol):
    async def reduce(
        self,
        messages: tuple[ModelMessage, ...],
        budget: ContextBudget,
        *,
        scope: ContextReductionScope | None = None,
    ) -> ContextProjection: ...
