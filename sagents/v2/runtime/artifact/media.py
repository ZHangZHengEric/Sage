"""Store audio/video attachments outside the conversation ledger."""

from __future__ import annotations

import base64
import hashlib
import re

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import AudioBlock, FileBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.runtime.artifact.contracts import ArtifactStore

MEDIA_URI_PREFIX = "sage-media:"
# Base64 adds a third; one attachment plus prompt must fit a 20 MB inline request.
MAX_INLINE_MEDIA_BYTES = 12 * 1024 * 1024


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
    return MEDIA_URI_PREFIX + artifact_id


async def hydrate_media_blocks(
    messages: tuple[ModelMessage, ...],
    store: ArtifactStore | None,
) -> tuple[ModelMessage, ...]:
    hydrated = []
    cache: dict[tuple[str, str], str] = {}
    for message in messages:
        blocks = []
        for block in message.content:
            if not isinstance(
                block, (AudioBlock, FileBlock)
            ) or not block.uri.startswith(MEDIA_URI_PREFIX):
                blocks.append(block)
                continue
            artifact_id = block.uri.removeprefix(MEDIA_URI_PREFIX)
            mime_type = block.mime_type
            prefix = "audio/" if isinstance(block, AudioBlock) else "video/"
            if (
                store is None
                or not re.fullmatch(r"media-[0-9a-f]{64}", artifact_id)
                or not mime_type
                or not mime_type.startswith(prefix)
            ):
                raise _invalid_attachment()
            key = (artifact_id, mime_type)
            if key not in cache:
                reference, content = await store.get(artifact_id)
                if reference.media_type != mime_type or not (
                    0 < reference.size_bytes <= MAX_INLINE_MEDIA_BYTES
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
