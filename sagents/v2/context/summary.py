"""Conversation-summary port and helpers. Implementations live in context/plugins/."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from pydantic import Field

from sagents.v2.prompt_i18n import prompt_language
from sagents.v2.contracts.common import StrictModel, new_id, utc_now
from sagents.v2.context.contracts import ContextReductionScope
from sagents.v2.context.message_time import historical_time_context
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.contracts.items import (
    AudioBlock,
    FileBlock,
    ImageBlock,
    JsonBlock,
    ResourceRefBlock,
    TextBlock,
)


_DATA_URL_PATTERN = re.compile(
    r"data:([^;,\s]+);base64,([A-Za-z0-9+/=_-]+)",
    re.IGNORECASE,
)


def _redact_data_urls(value: str) -> str:
    if "data:" not in value:
        return value

    def replacement(match: re.Match[str]) -> str:
        return (
            f"<redacted data URL; mime={match.group(1)}; "
            f"base64_len={len(match.group(2))}>"
        )

    return _DATA_URL_PATTERN.sub(replacement, value)


def _summary_safe_json(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_data_urls(value)
    if isinstance(value, dict):
        return {key: _summary_safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_summary_safe_json(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_summary_safe_json(item) for item in value)
    return value


def summary_safe_block_text(block: Any) -> str:
    """Render a content block for summaries without copying opaque media data."""
    if isinstance(block, TextBlock):
        return _redact_data_urls(block.text)
    if isinstance(block, JsonBlock):
        return json.dumps(
            _summary_safe_json(block.value),
            ensure_ascii=False,
            sort_keys=True,
        )
    if isinstance(block, ImageBlock):
        alt = f", alt={_redact_data_urls(block.alt)[:200]}" if block.alt else ""
        return f"[image attached: mime={block.mime_type}{alt}]"
    if isinstance(block, AudioBlock):
        return f"[audio attached: mime={block.mime_type}]"
    if isinstance(block, FileBlock):
        return (
            f"[file attached: name={block.name[:200]}, "
            f"mime={block.mime_type or 'unknown'}]"
        )
    if isinstance(block, ResourceRefBlock):
        name = f", name={block.name[:200]}" if block.name else ""
        return f"[resource attached: mime={block.mime_type or 'unknown'}{name}]"
    return f"[{getattr(block, 'kind', 'attachment')} attached]"


def summary_message_text(message: ModelMessage) -> str:
    text = "\n".join(summary_safe_block_text(block) for block in message.content)
    time = historical_time_context(message) if message.role == "user" else None
    return f"{time}\n{text}" if time else text


def summary_message_fragments(message: ModelMessage, language: str) -> Iterator[str]:
    """Render only the evidence that the text summarizer can consume."""
    from sagents.v2.prompt_i18n import prompt_text

    yield f"<{message.role}>\n"
    time = historical_time_context(message) if message.role == "user" else None
    if time:
        yield time
        yield "\n"
    for index, block in enumerate(message.content):
        if index:
            yield "\n"
        yield summary_safe_block_text(block)
    if message.tool_calls:
        yield f"\n{prompt_text('summary_tools', language)} "
        for index, call in enumerate(message.tool_calls):
            if index:
                yield ", "
            yield f"{call.name}("
            yield summary_safe_block_text(JsonBlock(value=call.arguments))
            yield ")"
    yield f"\n</{message.role}>"


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
    estimated_tokens: int = Field(default=0, ge=0)  # legacy snapshot field
    source_sequence: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


@dataclass
class SummaryValidation:
    """One verified prefix of the immutable ledger during a Run drive."""

    run_id: str | None
    digests: tuple[str, ...] = ()
    messages: tuple[ModelMessage, ...] = ()
    token: object = field(default_factory=object)

    def matches(
        self, digests: tuple[str, ...], messages: tuple[ModelMessage, ...]
    ) -> bool:
        return self.digests == digests and self.matches_messages(messages)

    def matches_messages(self, messages: tuple[ModelMessage, ...]) -> bool:
        return (
            len(self.messages) == len(messages)
            and all(previous is current for previous, current in zip(self.messages, messages))
        )

    def remember(self, digests: tuple[str, ...], messages: tuple[ModelMessage, ...]) -> None:
        self.messages = messages
        self.digests = digests
        self.token = object()


active_summary_validation: ContextVar[SummaryValidation | None] = ContextVar(
    "active_summary_validation", default=None
)


@contextmanager
def reuse_summary_validation(run_id: str):
    validation = SummaryValidation(run_id)
    token = active_summary_validation.set(validation)
    try:
        yield
    finally:
        validation.run_id = None
        validation.messages = ()
        validation.digests = ()
        active_summary_validation.reset(token)


def verified_summary_prefix_token(run_id: str, messages: tuple[ModelMessage, ...]) -> object | None:
    validation = active_summary_validation.get()
    if messages and validation is not None and validation.run_id == run_id:
        if validation.matches_messages(messages):
            return validation.token
    return None


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
    return prompt_language(value)


class ConversationSummarizer(Protocol):
    async def summarize(self, request: SummarizationRequest) -> str: ...


def message_digest(
    message: ModelMessage, *, include_source_metadata: bool = False
) -> str:
    value = message.model_dump(mode="json")
    if not include_source_metadata:
        # Event reconstruction adds provenance that the active Run ledger does
        # not carry. It must not invalidate an otherwise identical summary.
        value["metadata"] = {
            key: item
            for key, item in value["metadata"].items()
            if key not in {"source_session_id", "source_run_id", "source_item_id"}
        }
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


async def message_digests_async(messages, *, include_source_metadata: bool = False):
    from sagents.v2.concurrency import bounded_to_thread

    # Capture the ledger order. Each digest serializes its frozen ModelMessage
    # into a private JSON value, without cloning the whole prefix first.
    snapshot = tuple(messages)

    def digest_snapshot():
        return tuple(
            message_digest(message, include_source_metadata=include_source_metadata)
            for message in snapshot
        )

    return await bounded_to_thread("context-cpu", digest_snapshot)


def create_summary(
    *,
    scope: ContextReductionScope,
    previous: ConversationSummary | None,
    covered_messages: tuple[ModelMessage, ...],
    covered_digests: tuple[str, ...],
    text: str,
) -> ConversationSummary:
    now = utc_now()
    source_payload = "\n".join(covered_digests).encode()
    return ConversationSummary(
        summary_id=previous.summary_id if previous else new_id("context_summary"),
        context_key=scope.context_key,
        session_id=scope.session_id,
        revision=(previous.revision + 1) if previous else 1,
        source_digest=f"sha256:{hashlib.sha256(source_payload).hexdigest()}",
        covered_message_digests=covered_digests,
        source_message_count=len(covered_messages),
        text=text,
        source_sequence=scope.source_sequence,
        created_at=previous.created_at if previous else now,
        updated_at=now,
    )


async def completed_events(
    stream: AsyncIterator,
) -> list:
    """Test/support helper retained here to avoid SDK-specific accumulation."""

    return [event async for event in stream]
