"""Decorator-backed V2 image context Tool."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import urlparse

from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.tool import SideEffectLevel, ToolExecutionResult, ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime


class MediaTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

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
        run_id = invocation.call.owner_run_id if invocation is not None else session_id
        if self.runtime.image_context_publisher is not None:
            return await self.runtime.image_context_publisher(
                image_path=image_path, prompt=prompt, run_id=run_id
            )
        parsed = urlparse(image_path)
        if parsed.scheme in {"http", "https"}:
            assert invocation is not None
            response = await self.runtime.network_request(
                image_path,
                invocation,
                timeout_seconds=30,
                headers={"accept": "image/*"},
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}")
            data = response.body
            mime = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        else:
            assert invocation is not None
            data = await self.runtime.read_bytes(image_path, invocation)
            mime = (
                mimetypes.guess_type(PurePosixPath(image_path).name)[0] or "image/jpeg"
            )
        if not mime.startswith("image/"):
            raise ValueError(f"unsupported image type: {mime}")
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        text = prompt or f"Inspect the attached image from {image_path}."
        assert invocation is not None
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id,
            operation_id=invocation.call.operation_id,
            content=(
                TextBlock(text=text),
                ImageBlock(uri=uri, mime_type=mime, alt=image_path),
            ),
            metadata={"image_path": image_path, "native_multimodal": True},
        )
