"""Decorator-backed V2 image context Tool."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from PIL import Image, ImageOps

from sagents.v2._concurrency import bounded_to_thread
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import ImageBlock, JsonBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.tool import SideEffectLevel, ToolExecutionResult, ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime

# V2 carries its own copy rather than importing the V1 helper: V2 is built to
# stand alone, and a model-facing byte budget is not a detail worth coupling
# two implementations over.
_MAX_IMAGE_EDGE = 1536
# Budget for one compressed image. Base64 inflates it by roughly a third.
_TARGET_IMAGE_BYTES = 4 * 1024 * 1024
_JPEG_QUALITY = 85
_MIN_JPEG_QUALITY = 60
_FALLBACK_IMAGE_EDGES = (1280, 1024, 768, 512)
_IMAGE_HEADERS = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"BM",
)


def _normalize_image_for_jpeg(image: Image.Image) -> Image.Image:
    """Apply EXIF orientation, flatten transparency onto white, convert to RGB."""

    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        if image.mode == "P":
            image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        mask = image.split()[-1] if image.mode in ("RGBA", "LA") else None
        background.paste(image.convert("RGBA"), mask=mask)
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def _candidate_edges(max_edge: int) -> list[int]:
    edges = [max_edge, *(edge for edge in _FALLBACK_IMAGE_EDGES if edge < max_edge)]
    return list(dict.fromkeys(edge for edge in edges if edge > 0))


def compress_image_to_jpeg_bytes_for_llm(
    image: Image.Image,
    *,
    max_edge: int = _MAX_IMAGE_EDGE,
    target_bytes: int = _TARGET_IMAGE_BYTES,
    quality: int = _JPEG_QUALITY,
) -> bytes:
    """Encode as JPEG, giving up resolution and then quality to fit the budget.

    The smallest encoding seen is kept as a fallback: an image that cannot be
    squeezed under the budget is still better sent smaller than sent whole.
    """

    base = _normalize_image_for_jpeg(image)
    best: bytes | None = None
    for edge in _candidate_edges(max_edge):
        resized = base.copy()
        resized.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        for step in range(quality, _MIN_JPEG_QUALITY - 1, -5):
            output = io.BytesIO()
            resized.save(output, format="JPEG", quality=step)
            data = output.getvalue()
            if best is None or len(data) < len(best):
                best = data
            if len(data) <= target_bytes:
                return data
    assert best is not None
    return best


def local_image_path(uri: str) -> str | None:
    """Return a filesystem path for a local image URI; remote and data URLs stay None."""

    value = str(uri or "")
    if not value or value.startswith("data:"):
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            path = f"/{parsed.netloc}{path}"
        return path or None
    if parsed.scheme:
        return None
    return value


def ledger_image_uri(uri: str, *, image_path: str | None = None) -> str | None:
    """Keep a path or remote URL; never persist inline JPEG bytes."""

    value = str(uri or "")
    if value.startswith("data:"):
        path = str(image_path or "").strip()
        return path or None
    return value or None


async def hydrate_image_blocks(messages: tuple[ModelMessage, ...]):
    """Copy ledger messages and inline local files for one model request only."""

    hydrated = []
    changed = False
    for message in messages:
        if not any(
            isinstance(block, ImageBlock) and local_image_path(block.uri)
            for block in message.content
        ):
            hydrated.append(message)
            continue
        blocks = []
        message_changed = False
        for block in message.content:
            if not isinstance(block, ImageBlock):
                blocks.append(block)
                continue
            path = local_image_path(block.uri)
            if path is None:
                blocks.append(block)
                continue
            inlined = await _inline_local_image(block, path)
            blocks.append(inlined)
            message_changed = message_changed or inlined is not block
        if message_changed:
            hydrated.append(message.model_copy(update={"content": tuple(blocks)}))
            changed = True
        else:
            hydrated.append(message)
    return tuple(hydrated) if changed else messages


async def _inline_local_image(block: ImageBlock, path: str) -> ImageBlock:
    def encode():
        with Image.open(path) as image:
            return compress_image_to_jpeg_bytes_for_llm(image)

    try:
        data = await bounded_to_thread("context-cpu", encode)
    except (OSError, ValueError, Image.DecompressionBombError):
        return block
    return block.model_copy(
        update={
            "uri": f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}",
            "mime_type": "image/jpeg",
        }
    )


class MediaTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    def _error_result(
        self,
        invocation: ToolInvocation,
        image_path: str,
        message: str,
        reason: str,
        *,
        resolved_path: str | None = None,
    ) -> ToolExecutionResult:
        data = {"image_path": image_path, "reason": reason}
        if resolved_path and resolved_path != image_path:
            data["resolved_path"] = resolved_path
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id,
            operation_id=invocation.call.operation_id,
            content=(
                JsonBlock(
                    value={
                        "status": "error",
                        "message": message,
                        "data": data,
                    }
                ),
            ),
        )

    @tool(
        description="Attach an image to the next multimodal model turn.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def analyze_image(
        self,
        image_path: str,
        session_id: str,
        prompt: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> ToolExecutionResult | dict:
        capability = getattr(self.runtime, "supports_multimodal_input", None)
        if callable(capability) and invocation is not None:
            capability = capability(invocation.call.owner_agent_id)
        if capability is False:
            assert invocation is not None
            return self._error_result(
                invocation,
                image_path,
                "The current model does not support image input. Select a vision-capable model.",
                "multimodal_unsupported",
            )
        run_id = invocation.call.owner_run_id if invocation is not None else session_id
        if self.runtime.image_context_publisher is not None:
            return await self.runtime.image_context_publisher(
                image_path=image_path, prompt=prompt, run_id=run_id
            )
        assert invocation is not None
        parsed = urlparse(image_path)
        if parsed.scheme in {"http", "https"}:
            uri = image_path
            mime = mimetypes.guess_type(parsed.path)[0] or "image/jpeg"
            image_format = "remote_url"
        else:
            try:
                data = await self.runtime.read_bytes(image_path, invocation)
            except FileNotFoundError as exc:
                resolved = getattr(exc, "filename", None) or str(exc).strip() or None
                return self._error_result(
                    invocation,
                    image_path,
                    f"Image file not found: {image_path}",
                    "not_found",
                    resolved_path=resolved,
                )
            except (SageV2Error, PermissionError, OSError, ValueError) as exc:
                reason = (
                    "permission_denied"
                    if isinstance(exc, (SageV2Error, PermissionError))
                    else "unreadable"
                )
                return self._error_result(
                    invocation,
                    image_path,
                    f"Failed to read image {image_path}: {exc}",
                    reason,
                )
            mime = (
                mimetypes.guess_type(PurePosixPath(image_path).name)[0] or "image/jpeg"
            )
            if not mime.startswith("image/"):
                return self._error_result(
                    invocation,
                    image_path,
                    f"Unsupported image type: {mime}",
                    "unsupported_type",
                )

            def validate():
                if not (
                    any(data.startswith(header) for header in _IMAGE_HEADERS)
                    or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
                ):
                    raise ValueError("unrecognized image header")
                with Image.open(io.BytesIO(data)) as image:
                    _normalize_image_for_jpeg(image)

            try:
                await bounded_to_thread("context-cpu", validate)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                return self._error_result(
                    invocation,
                    image_path,
                    f"Invalid or unsupported image: {exc}",
                    "invalid_image",
                )
            mime = "image/jpeg"
            uri = image_path
            image_format = mime
        text = (
            prompt.strip()
            if prompt and prompt.strip()
            else f"Inspect the attached image from {image_path}."
        )
        guidance_id = new_id("image_guidance")
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id,
            operation_id=invocation.call.operation_id,
            content=(
                JsonBlock(
                    value={
                        "status": "success",
                        "message": "Image attached to the next multimodal model turn.",
                        "data": {
                            "image_path": image_path,
                            "image_format": image_format,
                            "guidance_id": guidance_id,
                            "mode": "native_multimodal_context",
                        },
                    }
                ),
            ),
            metadata={
                "image_path": image_path,
                "native_multimodal": True,
                "followup_user_message": {
                    "role": "user",
                    "content": [
                        {"kind": "text", "text": text},
                        {
                            "kind": "image",
                            "uri": uri,
                            "mime_type": mime,
                            "alt": image_path,
                        },
                    ],
                    "metadata": {
                        "tool_source": "analyze_image",
                        "tool_context": True,
                        "source_tool_call_id": invocation.call.tool_call_id,
                        "image_path": image_path,
                        "image_context_mode": "native_multimodal",
                        "hidden_from_chat": True,
                        "sse_visible": False,
                        "guidance_id": guidance_id,
                    },
                },
            },
        )
