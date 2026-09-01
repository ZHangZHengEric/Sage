"""Conversation-summary port and helpers. Implementations live in context/plugins/."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from pydantic import Field

from sagents.v2.contracts.common import StrictModel, new_id, utc_now
from sagents.v2.context.contracts import ContextReductionScope
from sagents.v2.context.token_estimator import TokenEstimator
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.contracts.items import TextBlock


class ConversationSummary(StrictModel):
    """Derived state; canonical conversation Items remain untouched."""

    summary_id: str
    context_key: str
    session_id: str
    revision: int = Field(ge=1)
    source_digest: str
    covered_message_digests: tuple[str, ...]
    source_message_count: int = Field(ge=1)
    text: str
    estimated_tokens: int = Field(ge=0)
    source_sequence: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class ConversationSummaryStore(Protocol):
    """Persistence port; implementations need not use a filesystem."""

    async def get(
        self, context_key: str, *, session_id: str | None = None
    ) -> ConversationSummary | None: ...

    async def save(
        self,
        summary: ConversationSummary,
        *,
        expected_revision: int | None,
    ) -> ConversationSummary: ...

    async def delete(
        self,
        context_key: str,
        *,
        expected_revision: int | None = None,
        session_id: str | None = None,
    ) -> None: ...


class SummarizationRequest(StrictModel):
    scope: ContextReductionScope
    messages: tuple[ModelMessage, ...]
    previous_summary: str | None = None
    target_tokens: int = Field(gt=0)

    @property
    def response_language(self) -> str:
        return _summary_language(self.scope.response_language)


def _summary_language(value: str | None) -> str:
    normalized = str(value or "en").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("pt"):
        return "pt"
    return "en"


class ConversationSummarizer(Protocol):
    async def summarize(self, request: SummarizationRequest) -> str: ...


def message_digest(message: ModelMessage) -> str:
    payload = json.dumps(
        message.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def create_summary(
    *,
    scope: ContextReductionScope,
    previous: ConversationSummary | None,
    covered_messages: tuple[ModelMessage, ...],
    covered_digests: tuple[str, ...],
    text: str,
    estimator: TokenEstimator,
) -> ConversationSummary:
    now = utc_now()
    source_payload = "\n".join(covered_digests).encode()
    summary_message = ModelMessage(role="system", content=(TextBlock(text=text),))
    return ConversationSummary(
        summary_id=previous.summary_id if previous else new_id("context_summary"),
        context_key=scope.context_key,
        session_id=scope.session_id,
        revision=(previous.revision + 1) if previous else 1,
        source_digest=f"sha256:{hashlib.sha256(source_payload).hexdigest()}",
        covered_message_digests=covered_digests,
        source_message_count=len(covered_messages),
        text=text,
        estimated_tokens=estimator.estimate((summary_message,)),
        source_sequence=scope.source_sequence,
        created_at=previous.created_at if previous else now,
        updated_at=now,
    )


async def completed_events(
    stream: AsyncIterator,
) -> list:
    """Test/support helper retained here to avoid SDK-specific accumulation."""

    return [event async for event in stream]
