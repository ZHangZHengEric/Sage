from __future__ import annotations

from a2a.types.a2a_pb2 import Message

from app.server_v2.conversations.agui.mapping import validate_agui_id
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import ImageBlock, TextBlock

# A2A identity, expressed in Sage terms:
#   Task.id        -> run_id      (one A2A Task is one Sage Run)
#   Task.contextId -> session_id  (an A2A context is a Sage thread)
#   Message.messageId -> idempotency key, so a retried send never runs twice


def context_id(message: Message) -> str:
    """Return the thread this message belongs to, minting one when absent.

    A2A lets a client open a conversation without naming it. Sage always needs
    a session, so an absent context starts a new one rather than being an
    error — the caller learns the id from the Task it gets back.
    """

    raw = str(message.context_id or "").strip()
    if not raw:
        return new_id("a2a")
    return validate_agui_id(raw, field="contextId")


def message_id(message: Message) -> str:
    raw = str(message.message_id or "").strip()
    if not raw:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.a2a.mapping.validation",
                category=ErrorCategory.VALIDATION,
                message="messageId is required",
            )
        )
    return validate_agui_id(raw, field="messageId")


def to_start_run(
    message: Message,
    *,
    session_id: str,
    agent_id: str,
    composition_hash: str,
    enabled_skills: tuple[str, ...] | None = None,
    metadata: dict[str, object] | None = None,
) -> StartRun:
    return StartRun(
        session_id=session_id,
        agent_id=agent_id,
        input=(InputItem(role="user", content=to_blocks(message.parts)),),
        config=RunConfig(
            enabled_skills=enabled_skills,
            metadata=dict(metadata or {}),
        ),
        resolved_spec_hash=composition_hash,
        idempotency_key=message_id(message),
    )


def to_blocks(parts) -> tuple[TextBlock | ImageBlock, ...]:
    """Project A2A Parts onto Sage content blocks.

    A Part that Sage cannot carry as input — inline bytes, structured data — is
    rejected rather than silently dropped: a caller whose attachment vanished
    would otherwise get a confident answer about content the model never saw.
    """

    blocks: list[TextBlock | ImageBlock] = []
    for part in parts:
        field = part.WhichOneof("content")
        if field == "text":
            if part.text:
                blocks.append(TextBlock(text=part.text))
        elif field == "url":
            blocks.append(
                ImageBlock(uri=part.url, mime_type=part.media_type or "image/*")
            )
        else:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.a2a.mapping.validation",
                    category=ErrorCategory.VALIDATION,
                    message=f"unsupported message part: {field or 'empty'}",
                )
            )
    if not blocks:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.a2a.mapping.validation",
                category=ErrorCategory.VALIDATION,
                message="message has no supported content",
            )
        )
    return tuple(blocks)
