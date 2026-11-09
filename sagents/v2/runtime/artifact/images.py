"""Image snapshots referenced by the ledger and expanded only for inference."""

from __future__ import annotations

import asyncio
import base64
import os
import stat
from pathlib import Path
import hashlib
import re
from urllib.parse import parse_qs, urlparse

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import ImageBlock, TextBlock
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


# Compatibility for WishSeen messages admitted before inline image inputs.
# Signed URLs are identified, never downloaded or renewed.
WISHSEEN_FEEDBACK_ROOT = "server_v2.wishseen_feedback_root"
_WISHSEEN_IMAGES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_MAX_FEEDBACK_BYTES = 10 << 20


def wishseen_history_image_id(uri: str, tenant: str) -> str | None:
    if not re.fullmatch(r"[0-9]+", tenant) or not uri.startswith("https://"):
        return None
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if (parsed.netloc != "storage.withling.top"
            or not parse_qs(parsed.query).get("X-Amz-Signature")):
        return None
    match = re.fullmatch(r"/wishseen/media/" + tenant + r"/(m_[A-Za-z0-9_-]{1,38})", parsed.path)
    return match.group(1) if match else None


def read_wishseen_feedback(root: str, media_id: str, *, read_data: bool = True):
    if not re.fullmatch(r"m_[A-Za-z0-9_-]{1,38}", media_id):
        return None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = None
    try:
        # Open each component, including the project and uploads directories,
        # without following workspace-controlled symlinks.
        path = Path(root)
        if not path.is_absolute() or ".." in path.parts:
            return None
        parent = os.open(path.anchor, directory_flags)
        for part in path.parts[1:]:
            child = os.open(part, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        name = hashlib.sha256(media_id.encode()).hexdigest()[:24]
        for extension, mime in _WISHSEEN_IMAGES.items():
            try:
                fd = os.open(name + extension, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError:
                continue
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_FEEDBACK_BYTES:
                    continue
                if not read_data:
                    return True
                data = source.read(info.st_size + 1)
                after = os.fstat(source.fileno())
                if (len(data) == info.st_size == after.st_size
                        and info.st_mtime_ns == after.st_mtime_ns
                        and info.st_ctime_ns == after.st_ctime_ns):
                    return mime, data
    except OSError:
        return None
    finally:
        if parent is not None:
            os.close(parent)
    return None


async def hydrate_wishseen_history(messages, metadata):
    root = metadata.get(WISHSEEN_FEEDBACK_ROOT)
    tenant = metadata.get("server_v2.workspace_user_id")
    if not isinstance(root, str) or not isinstance(tenant, str):
        return messages

    def hydrate():
        cache = {}
        result = []
        for message in messages:
            if message.role != "user":
                result.append(message)
                continue
            blocks = []
            for block in message.content:
                media_id = wishseen_history_image_id(block.uri, tenant) if isinstance(block, ImageBlock) else None
                if media_id is None:
                    blocks.append(block)
                    continue
                if media_id not in cache:
                    found = read_wishseen_feedback(root, media_id)
                    if found is None:
                        cache[media_id] = TextBlock(text="[Earlier feedback image is unavailable.]")
                    else:
                        mime, data = found
                        uri = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
                        cache[media_id] = (mime, uri)
                replacement = cache[media_id]
                if isinstance(replacement, TextBlock):
                    blocks.append(replacement)
                else:
                    mime, uri = replacement
                    blocks.append(block.model_copy(update={"mime_type": mime, "uri": uri}))
            content = tuple(blocks)
            result.append(message if content == message.content else message.model_copy(update={"content": content}))
        return tuple(result)

    return await asyncio.to_thread(hydrate)
