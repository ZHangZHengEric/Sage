"""Store audio/video attachments outside the conversation ledger."""

from __future__ import annotations

import base64
import hashlib
import re

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import AudioBlock, FileBlock, TextBlock
from sagents.v2.model.contracts import ModelCapabilities, ModelMessage
from sagents.v2.runtime.artifact.contracts import ArtifactStore

MEDIA_URI_PREFIX = "sage-media:"
# Base64 adds a third; one attachment plus prompt must fit a 20 MB inline request.
MAX_INLINE_MEDIA_BYTES = 12 * 1024 * 1024
# Bound the total of decoded Session attachments separately from provider limits.
# Even an upload to object storage initially uses local memory.
_MAX_HYDRATED_BYTES = 32_000_000
_DEFAULT_REQUEST_BYTES = 20_000_000
_DEFAULT_VIDEO_PARTS = 10


def _attachment_id(mime_type: str, digest: str) -> str:
    return "media-" + hashlib.sha256(f"{mime_type}\0{digest}".encode()).hexdigest()


def _invalid_attachment() -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code="media.invalid_attachment",
            category=ErrorCategory.VALIDATION,
            message="Audio or video attachment is unavailable or invalid.",
            safe_to_resume=True,
        )
    )


async def snapshot_media(store: ArtifactStore, payload: bytes, mime_type: str) -> str:
    if not 0 < len(payload) <= MAX_INLINE_MEDIA_BYTES:
        raise _invalid_attachment()
    artifact_id = _attachment_id(mime_type, hashlib.sha256(payload).hexdigest())

    async def stream():
        yield payload

    await store.put(artifact_id=artifact_id, media_type=mime_type, content=stream())
    return f"{MEDIA_URI_PREFIX}{artifact_id}:{len(payload)}"


def _reference(block: AudioBlock | FileBlock) -> tuple[str, int | None]:
    artifact_id, separator, size = block.uri.removeprefix(MEDIA_URI_PREFIX).partition(":")
    if not re.fullmatch(r"media-[0-9a-f]{64}", artifact_id):
        raise _invalid_attachment()
    if not separator:
        return artifact_id, None  # References written before size was included.
    if not re.fullmatch(r"[1-9][0-9]{0,7}", size) or int(size) > MAX_INLINE_MEDIA_BYTES:
        raise _invalid_attachment()
    return artifact_id, int(size)


def _plan_hydration(messages, capabilities):
    remaining_hydrated = _MAX_HYDRATED_BYTES
    inline_budget = (
        capabilities.media_request_bytes if capabilities else None
    ) or _DEFAULT_REQUEST_BYTES
    text_bytes = sum(
        len(block.text.encode("utf-8"))
        for message in messages
        for block in message.content
        if isinstance(block, TextBlock)
    )
    remaining_inline = inline_budget - text_bytes
    videos = (capabilities.max_video_parts if capabilities else None) or _DEFAULT_VIDEO_PARTS
    decisions = {}
    for message_index in reversed(range(len(messages))):
        content = messages[message_index].content
        for block_index in reversed(range(len(content))):
            block = content[block_index]
            if not isinstance(block, (AudioBlock, FileBlock)):
                continue
            attachment = block.uri.startswith(MEDIA_URI_PREFIX)
            if isinstance(block, AudioBlock):
                kind = "audio"
            elif (block.mime_type or "").lower().startswith("video/"):
                kind = "video"
            else:
                if attachment:
                    raise _invalid_attachment()
                continue
            supported = capabilities is None or (
                capabilities.supports_audio_input if kind == "audio"
                else capabilities.supports_video_input
            ) is True
            index = (message_index, block_index)
            if not supported:
                if attachment:
                    decisions[index] = TextBlock(
                        text=f"[{kind.capitalize()} attachment omitted: the current model does not accept {kind} input.]"
                    )
                continue
            hosted = bool(capabilities and capabilities.hosts_inline_video and kind == "video")
            if not attachment:
                if kind == "video":
                    videos = max(0, videos - 1)
                if not hosted and block.uri.startswith("data:"):
                    remaining_inline -= len(block.uri)
                continue
            artifact_id, raw_size = _reference(block)
            # Treat legacy references without a hint as a maximum-sized file.
            wire_size = 4 * (((raw_size or MAX_INLINE_MEDIA_BYTES) + 2) // 3) + 256
            if (
                (kind == "video" and videos == 0)
                or wire_size > remaining_hydrated
                or (not hosted and wire_size > remaining_inline)
            ):
                decisions[index] = TextBlock(
                    text=f"[{kind.capitalize()} attachment omitted from this model request because of the request limits.]"
                )
                continue
            decisions[index] = (artifact_id, raw_size)
            remaining_hydrated -= wire_size
            if not hosted:
                remaining_inline -= wire_size
            if kind == "video":
                videos -= 1
    return decisions


async def hydrate_media_blocks(
    messages: tuple[ModelMessage, ...],
    store: ArtifactStore | None,
    capabilities: ModelCapabilities | None = None,
) -> tuple[ModelMessage, ...]:
    if not any(
        isinstance(block, (AudioBlock, FileBlock)) and block.uri.startswith(MEDIA_URI_PREFIX)
        for message in messages
        for block in message.content
    ):
        return messages
    decisions = _plan_hydration(messages, capabilities)
    hydrated = []
    cache: dict[tuple[str, str, int | None], str] = {}
    for message_index, message in enumerate(messages):
        blocks = []
        for block_index, block in enumerate(message.content):
            decision = decisions.get((message_index, block_index))
            if decision is None or isinstance(decision, TextBlock):
                blocks.append(block if decision is None else decision)
                continue
            artifact_id, raw_size = decision
            mime_type = block.mime_type
            prefix = "audio/" if isinstance(block, AudioBlock) else "video/"
            if (
                store is None
                or not mime_type
                or not mime_type.startswith(prefix)
            ):
                raise _invalid_attachment()
            key = (artifact_id, mime_type, raw_size)
            if key not in cache:
                reference, content = await store.get(artifact_id)
                if (
                    reference.media_type != mime_type
                    or not 0 < reference.size_bytes <= MAX_INLINE_MEDIA_BYTES
                    or (raw_size is not None and reference.size_bytes != raw_size)
                ):
                    raise _invalid_attachment()
                payload = bytearray()
                async for chunk in content:
                    if len(payload) + len(chunk) > reference.size_bytes:
                        raise _invalid_attachment()
                    payload.extend(chunk)
                digest = hashlib.sha256(payload).hexdigest()
                if (
                    len(payload) != reference.size_bytes
                    or reference.digest != "sha256:" + digest
                    or _attachment_id(mime_type, digest) != artifact_id
                ):
                    raise _invalid_attachment()
                cache[key] = f"data:{mime_type};base64," + base64.b64encode(
                    payload
                ).decode("ascii")
            blocks.append(block.model_copy(update={"uri": cache[key]}))
        content = tuple(blocks)
        hydrated.append(
            message
            if content == message.content
            else message.model_copy(update={"content": content})
        )
    return tuple(hydrated)
