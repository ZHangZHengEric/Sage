from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ag_ui.core import RunAgentInput
from pydantic import TypeAdapter

from app.server_v2.core.errors import ServerV2Error
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.common import Identifier
from sagents.v2.contracts.items import ImageBlock, TextBlock

_ID = TypeAdapter(Identifier)


def validate_agui_id(value: str, *, field: str) -> str:
    candidate = str(value or "").strip()
    if candidate in {".", ".."} or "/" in candidate or "\\" in candidate:
        raise ServerV2Error("validation", f"{field} is invalid")
    try:
        return _ID.validate_python(candidate)
    except Exception as exc:
        raise ServerV2Error("validation", f"{field} is invalid") from exc


def _forwarded_props(request: RunAgentInput) -> Mapping[str, Any]:
    props = request.forwarded_props
    if props is None:
        return {}
    if not isinstance(props, Mapping):
        raise ServerV2Error("validation", "forwardedProps must be an object")
    return props


def _content_blocks(content: Any) -> tuple[TextBlock | ImageBlock, ...]:
    if isinstance(content, str):
        text = content.strip()
        if not text:
            raise ServerV2Error("validation", "user message is empty")
        return (TextBlock(text=text),)
    if not isinstance(content, list):
        raise ServerV2Error("validation", "user message content is invalid")
    blocks: list[TextBlock | ImageBlock] = []
    for part in content:
        if hasattr(part, "model_dump"):
            value = part.model_dump(by_alias=True, exclude_none=True, mode="json")
        elif isinstance(part, Mapping):
            value = dict(part)
        else:
            continue
        part_type = value.get("type")
        if part_type == "text":
            text = str(value.get("text") or "")
            if text:
                blocks.append(TextBlock(text=text))
        elif part_type == "image":
            source = value.get("source")
            if (
                isinstance(source, Mapping)
                and source.get("type") == "url"
                and source.get("value")
            ):
                blocks.append(
                    ImageBlock(uri=str(source["value"]), mime_type="image/*")
                )
            elif value.get("url"):
                blocks.append(ImageBlock(uri=str(value["url"]), mime_type="image/*"))
    if not blocks:
        raise ServerV2Error("validation", "user message is empty")
    return tuple(blocks)


def latest_user_input(request: RunAgentInput) -> InputItem:
    users = [
        message
        for message in request.messages
        if getattr(message, "role", None) == "user"
    ]
    if not users:
        raise ServerV2Error("validation", "at least one user message is required")
    return InputItem(role="user", content=_content_blocks(getattr(users[-1], "content", "")))


def to_start_run(
    request: RunAgentInput,
    *,
    composition_hash: str,
    default_agent_id: str,
    enabled_skills: tuple[str, ...] | None = None,
) -> tuple[str, str, str, StartRun]:
    thread_id = validate_agui_id(request.thread_id, field="threadId")
    run_id = validate_agui_id(request.run_id, field="runId")
    props = _forwarded_props(request)
    agent_id = str(props.get("agentId") or default_agent_id).strip() or default_agent_id
    command = StartRun(
        session_id=thread_id,
        agent_id=agent_id,
        input=(latest_user_input(request),),
        config=RunConfig(enabled_skills=enabled_skills),
        resolved_spec_hash=composition_hash,
        idempotency_key=run_id,
    )
    return thread_id, run_id, agent_id, command
