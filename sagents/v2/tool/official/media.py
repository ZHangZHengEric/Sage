"""Decorator-backed V2 image context Tool."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import urlparse

from PIL import Image

from sagents.utils.multimodal_image import compress_image_to_jpeg_bytes_for_llm
from sagents.v2._concurrency import bounded_to_thread
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import JsonBlock
from sagents.v2.tool import SideEffectLevel, ToolExecutionResult, ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime


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

            def normalize():
                with Image.open(io.BytesIO(data)) as image:
                    return compress_image_to_jpeg_bytes_for_llm(image)

            try:
                data = await bounded_to_thread("context-cpu", normalize)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                return self._error_result(
                    invocation,
                    image_path,
                    f"Invalid or unsupported image: {exc}",
                    "invalid_image",
                )
            mime = "image/jpeg"
            uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
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
