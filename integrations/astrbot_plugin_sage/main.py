"""AstrBot plugin entry point. Install this directory, without the Sage package."""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import httpx
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Image, Plain, Reply
from astrbot.api.star import Context, Star

from .bridge import MessageSource, SageBridge
from .client import BridgeError, SageClient
from .config import BridgeConfig


class SagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.settings = BridgeConfig.model_validate(dict(config))
        self.http = httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        self.bridge = SageBridge(
            self.settings, SageClient(self.http, self.settings), self
        )

    # Run before AstrBot's default and proactive Agent listeners. Bound robots
    # have one execution owner; commands for other robots remain unaffected.
    # https://docs.astrbot.app/dev/star/guides/listen-message-event.html
    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize)
    async def on_message(self, event: AstrMessageEvent) -> None:
        source = MessageSource(
            platform_id=event.get_platform_id(),
            origin=event.unified_msg_origin,
            sender_id=event.get_sender_id(),
            message_id=str(event.message_obj.message_id or ""),
        )
        if self.bridge.binding(source) is None:
            return
        event.should_call_llm(False)
        event.stop_event()
        if source.sender_id == event.get_self_id():
            return
        text = event.message_str.strip()
        if (
            not event.is_private_chat()
            and not event.is_at_or_wake_command
            and text.split(maxsplit=1)[:1] != ["/sage"]
        ):
            return
        try:
            self.bridge.authorize(source)
            if text == "/sage":
                reply = "Sage：直接发送文本或图片；/sage status 查询；/sage cancel 取消；/sage new 新会话。"
            elif text.split(maxsplit=1)[:1] == ["/sage"]:
                tokens = text.split()
                if len(tokens) != 2 or tokens[1] not in {"status", "cancel", "new"}:
                    raise BridgeError(
                        "支持 /sage status、/sage cancel 和 /sage new。",
                        "invalid_command",
                    )
                reply = (await self.bridge.handle(source, command=tokens[1])).text
            else:
                parts = await self._parts(event)
                reply = (await self.bridge.handle(source, parts)).text
        except BridgeError as exc:
            self.logger.warning("Sage bridge request failed (%s)", exc.code)
            reply = str(exc)
        except Exception:
            # Exception text can contain prompts, platform URLs or credentials.
            self.logger.error("Sage bridge request failed (unexpected_error)")
            reply = "Sage 连接暂时不可用，请联系管理员；已提交的任务可用 /sage status 核对。"
        if reply:
            if len(reply) > 12_000:
                reply = reply[:12_000] + "\n回复较长，完整结果请到 Sage Web 查看。"
            for offset in range(0, len(reply), 1500):
                await event.send(event.plain_result(reply[offset : offset + 1500]))

    async def _parts(self, event: AstrMessageEvent) -> list[dict]:
        parts = []
        image_bytes = 0
        text_size = 0
        for component in event.get_messages():
            if isinstance(component, Plain):
                text = component.text
            elif isinstance(component, Image):
                remaining = self.settings.max_image_bytes - image_bytes
                if remaining <= 0:
                    raise BridgeError("图片总大小超过连接限制。", "image_too_large")
                async with asyncio.timeout(self.settings.request_timeout_seconds):
                    path = await component.convert_to_file_path()
                raw, media_type = await asyncio.to_thread(_read_image, path, remaining)
                image_bytes += len(raw)
                encoded = base64.b64encode(raw).decode("ascii")
                parts.append(
                    {
                        "url": f"data:{media_type};base64,{encoded}",
                        "mediaType": media_type,
                    }
                )
                continue
            elif isinstance(component, Reply):
                text = (
                    f"[引用消息] {component.message_str}"
                    if component.message_str
                    else ""
                )
            elif isinstance(component, At):
                text = (
                    ""
                    if str(component.qq) == str(event.get_self_id())
                    else f"@{component.qq}"
                )
            else:
                raise BridgeError(
                    "当前桥接支持文本和图片；此消息未提交，请移除其他附件后重试。",
                    "unsupported_media",
                )
            text_size += len(text)
            if text_size > 20_000:
                raise BridgeError(
                    "消息文本超过 20000 字符，请分开发送。", "message_too_large"
                )
            if text.strip():
                parts.append({"text": text})
        return parts

    async def terminate(self) -> None:
        await self.http.aclose()


def _read_image(path: str, limit: int) -> tuple[bytes, str]:
    file = Path(path)
    if not file.is_file() or file.stat().st_size > limit:
        raise BridgeError("图片不可读取或总大小超过连接限制。", "image_too_large")
    with file.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise BridgeError("图片总大小超过连接限制。", "image_too_large")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif raw.startswith((b"GIF87a", b"GIF89a")):
        media_type = "image/gif"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        media_type = "image/webp"
    else:
        raise BridgeError(
            "图片格式不支持，请使用 PNG、JPEG、GIF 或 WebP。", "unsupported_image"
        )
    return raw, media_type
