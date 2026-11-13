"""Keep recent images inline while enforcing provider request budgets."""

import base64
import io
import math
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

from sagents.v2.concurrency import bounded_to_thread

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.workspace_images import (
    materialize_image_source,
    minimum_workspace_image_path,
)


OPENAI_MAX_REQUEST_BYTES = 512_000_000
OPENAI_MAX_IMAGES = 1_500
# Apply the Chat Completions 8 MB guidance conservatively to encoded input.
OPENAI_INLINE_IMAGE_BYTES = 8_000_000
OPENAI_INLINE_IMAGE_EDGE = 6_000
OPENAI_MAX_IMAGE_PATCHES = 30_000
COMPATIBLE_MAX_REQUEST_BYTES = 32_000_000
# Bound the memory required to decode an oversized compressed image.
_MAX_REENCODE_PIXELS = 64_000_000


def json_bytes(body) -> int:
    return len(httpx.Request("POST", "https://example.invalid", json=body).content)


def _openai_request_body(payload):
    body = {**payload, **payload.get("extra_body", {})}
    body.pop("extra_body", None)
    return body


def request_too_large(size: int, limit: int) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="model.request_too_large",
        category=ErrorCategory.VALIDATION,
        message=f"Model request uses {size} bytes and exceeds the {limit}-byte limit.",
        metadata={"request_bytes": size, "max_request_bytes": limit},
        safe_to_resume=True,
    ))


def _compress_source(source, *, max_bytes, max_edge, max_patches):
    encoded = source["data"]
    oversized = len(encoded) > max_bytes
    try:
        with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
            width, height = image.size
            scale = min(1.0, max_edge / max(width, height))
            if max_patches is not None:
                while (
                    math.ceil(max(1, int(width * scale)) / 32)
                    * math.ceil(max(1, int(height * scale)) / 32)
                    > max_patches
                ):
                    scale *= 0.98
            if scale == 1.0 and not oversized:
                return None, False
            if width * height > _MAX_REENCODE_PIXELS:
                return None, True

            normalized = ImageOps.exif_transpose(image)
            width, height = normalized.size
            alpha = "A" in normalized.getbands() or "transparency" in normalized.info
            normalized = normalized.convert("RGBA" if alpha else "RGB")
            image_format, mime = ("WEBP", "image/webp") if alpha else ("JPEG", "image/jpeg")
            for _ in range(6):
                size = (max(1, int(width * scale)), max(1, int(height * scale)))
                resized = normalized.resize(size, Image.Resampling.LANCZOS) if size != normalized.size else normalized
                for quality in (90, 82, 74):
                    with io.BytesIO() as output:
                        resized.save(output, format=image_format, quality=quality)
                        raw = output.getvalue()
                    if 4 * ((len(raw) + 2) // 3) <= max_bytes:
                        return {
                            "type": "base64", "media_type": mime,
                            "data": base64.b64encode(raw).decode("ascii"),
                        }, False
                scale *= 0.8
    except Image.DecompressionBombError:
        return None, True
    except (OSError, ValueError, SyntaxError):
        # Preserve provider validation for malformed inputs within the byte budget.
        return None, oversized
    return None, True


async def compress_wire_images(images, *, source_for, update, max_bytes, max_edge, max_patches=None):
    """Normalize only oversized inline images and retain original fallback bytes."""
    originals = {}
    unresolved = set()
    cache = {}
    for image in images:
        source = source_for(image)
        if source.get("type") != "base64":
            continue
        key = (source["media_type"], source["data"])
        if key not in cache:
            cache[key] = await bounded_to_thread(
                "context-cpu",
                lambda: _compress_source(
                    source, max_bytes=max_bytes, max_edge=max_edge, max_patches=max_patches,
                ),
            )
        compressed, exceeds = cache[key]
        if compressed is not None:
            originals[id(image)] = source
            update(image, compressed)
        elif exceeds:
            unresolved.add(id(image))
    return originals, unresolved


async def limit_wire_images(images, *, size, max_bytes, max_images, exceeds, source_for, text_type):
    """Replace mandatory outliers, then the oldest images until both budgets fit."""
    remaining = len(images)
    paths = {}
    unavailable = None
    for image in images:
        if not exceeds(image):
            continue
        size += await _replace(image, source_for, text_type, paths)
        remaining -= 1

    for image in images:
        if remaining <= max_images and size <= max_bytes:
            break
        if image["type"] == text_type:
            continue
        if remaining <= max_images and json_bytes(image) <= json_bytes(
            _reference_block(image, text_type, minimum_workspace_image_path())
        ):
            # Short URL blocks may use fewer bytes than a workspace reference.
            continue
        try:
            size += await _replace(image, source_for, text_type, paths)
        except SageV2Error as exc:
            if (
                exc.info.code != "model.image_workspace_unavailable"
                or source_for(image).get("type") != "url"
            ):
                raise
            unavailable = exc
            # Other images can still satisfy the count or size budget.
            continue
        remaining -= 1
    if remaining > max_images and unavailable is not None:
        raise unavailable


async def _replace(image, source_for, text_type, paths):
    source = source_for(image)
    key = tuple(source.items())
    if key not in paths:
        paths[key] = await materialize_image_source(source)
    replacement = _reference_block(image, text_type, paths[key])
    change = json_bytes(replacement) - json_bytes(image)
    image.clear()
    image.update(replacement)
    return change


def _reference_block(image, text_type, path):
    replacement = {"type": text_type, "text": f"[Workspace image: {path}]"}
    if "cache_control" in image:
        replacement["cache_control"] = image["cache_control"]
    return replacement


async def limit_openai_images(
    payload, config, *, responses: bool, original_sources=None, retry_below=None,
    already_compressed=False,
) -> int:
    field, image_type, text_type = (
        ("input", "input_image", "input_text") if responses
        else ("messages", "image_url", "text")
    )
    images = [
        part
        for message in payload[field]
        for key in ("content", "output")
        if isinstance(message.get(key), list)
        for part in message[key]
        if isinstance(part, dict) and part.get("type") == image_type
    ]
    body = _openai_request_body(payload)
    limit = config.max_request_bytes
    if limit is None:
        direct = urlsplit(config.base_url).hostname == "api.openai.com"
        limit = OPENAI_MAX_REQUEST_BYTES if direct else COMPATIBLE_MAX_REQUEST_BYTES
    if retry_below is not None:
        limit = min(limit, retry_below // 2)

    def url(image):
        value = image["image_url"]
        return value if responses else value["url"]

    def source_for(image):
        address = url(image)
        header, _, data = address.partition(",")
        if header.startswith("data:") and header.endswith(";base64"):
            return {"type": "base64", "media_type": header[5:-7], "data": data}
        return {"type": "url", "url": address}

    def update(image, source):
        address = f"data:{source['media_type']};base64,{source['data']}"
        if responses:
            image["image_url"] = address
        else:
            image["image_url"]["url"] = address

    if images:
        originals = original_sources if original_sources is not None else {}
        unresolved = set()
        if retry_below is None and not already_compressed:
            compressed, unresolved = await compress_wire_images(
                images, source_for=source_for, update=update,
                max_bytes=config.max_inline_image_bytes, max_edge=config.max_inline_image_edge,
                max_patches=OPENAI_MAX_IMAGE_PATCHES,
            )
            originals.update(compressed)
        await limit_wire_images(
            images, size=json_bytes(body), max_bytes=limit, max_images=config.max_inline_images,
            exceeds=lambda image: id(image) in unresolved,
            source_for=lambda image: originals.get(id(image)) or source_for(image),
            text_type=text_type,
        )
    size = json_bytes(body)
    if retry_below is None and size > limit:
        raise request_too_large(size, limit)
    return size


async def retry_openai_image_payload(payload, config, *, responses, original_sources, rejected_bytes, error):
    """Reserve at most one retry and only when the request actually shrank."""
    from sagents.v2.model.recovery_scope import reserve_additional_request

    smaller_bytes = await limit_openai_images(
        payload, config, responses=responses, original_sources=original_sources,
        retry_below=rejected_bytes,
    )
    if smaller_bytes >= rejected_bytes:
        return None
    await reserve_additional_request(
        "compatibility", purpose="openai_image_references",
        error=error.model_copy(update={"metadata": {
            **error.metadata, "request_bytes": rejected_bytes,
        }}),
    )
    return smaller_bytes
