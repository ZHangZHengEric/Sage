"""Image snapshots referenced by the ledger and expanded only for inference."""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urlparse

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import ImageBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.runtime.artifact.contracts import ArtifactStore

IMAGE_URI_PREFIX = "sage-image:"
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def image_error(code: str, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=ErrorCategory.VALIDATION,
            message=message,
            safe_to_resume=True,
        )
    )


async def snapshot_image(store: ArtifactStore, payload: bytes) -> str:
    if len(payload) > MAX_IMAGE_BYTES:
        raise image_error(
            "image.invalid_attachment", "Image attachment exceeds its size limit."
        )
    digest = hashlib.sha256(payload).hexdigest()

    async def stream():
        yield payload

    await store.put(
        artifact_id=digest,
        media_type="image/jpeg",
        content=stream(),
    )
    return IMAGE_URI_PREFIX + digest


async def hydrate_image_blocks(
    messages: tuple[ModelMessage, ...],
    store: ArtifactStore | None,
) -> tuple[ModelMessage, ...]:
    hydrated = []
    cache: dict[str, str] = {}
    for message in messages:
        blocks = []
        changed = False
        for block in message.content:
            if not isinstance(block, ImageBlock):
                blocks.append(block)
                continue
            if not block.uri.startswith(IMAGE_URI_PREFIX):
                # Inline legacy images and remote URLs never trigger host I/O.
                if urlparse(block.uri).scheme not in {"data", "http", "https"}:
                    raise image_error(
                        "image.local_path_unsupported",
                        "Local image paths must be attached through analyze_image.",
                    )
                blocks.append(block)
                continue
            digest = block.uri[len(IMAGE_URI_PREFIX) :]
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise image_error(
                    "image.invalid_reference", "Invalid image attachment reference."
                )
            if store is None:
                raise image_error(
                    "image.store_unavailable",
                    "Image attachment storage is unavailable.",
                )
            if digest not in cache:
                reference, content = await store.get(digest)
                if (
                    reference.media_type != "image/jpeg"
                    or reference.size_bytes > MAX_IMAGE_BYTES
                ):
                    raise image_error(
                        "image.invalid_attachment",
                        "Invalid image attachment type or size.",
                    )
                chunks = []
                size = 0
                async for chunk in content:
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise image_error(
                            "image.invalid_attachment",
                            "Image attachment exceeds its size limit.",
                        )
                    chunks.append(chunk)
                payload = b"".join(chunks)
                if (
                    len(payload) != reference.size_bytes
                    or hashlib.sha256(payload).hexdigest() != digest
                    or reference.digest != "sha256:" + digest
                ):
                    raise image_error(
                        "image.integrity_failed",
                        "Image attachment checksum does not match.",
                    )
                cache[digest] = "data:image/jpeg;base64," + base64.b64encode(
                    payload
                ).decode("ascii")
            blocks.append(
                block.model_copy(
                    update={"uri": cache[digest], "mime_type": "image/jpeg"}
                )
            )
            changed = True
        hydrated.append(
            message.model_copy(update={"content": tuple(blocks)})
            if changed
            else message
        )
    return tuple(hydrated)
