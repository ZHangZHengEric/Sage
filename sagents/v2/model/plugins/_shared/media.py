"""Audio/video block handling shared by model wire adapters."""

from __future__ import annotations

from typing import Literal

from sagents.v2.contracts.items import AudioBlock, FileBlock
from sagents.v2.model.contracts import ModelCapabilities

MediaKind = Literal["audio", "video"]


def media_kind(block: object) -> MediaKind | None:
    if isinstance(block, AudioBlock):
        return "audio"
    if isinstance(block, FileBlock) and block.mime_type:
        prefix = block.mime_type.split("/", 1)[0].lower()
        if prefix == "audio" or prefix == "video":
            return prefix
    return None


def accepts_media(capabilities: ModelCapabilities, kind: MediaKind) -> bool:
    value = (
        capabilities.supports_audio_input
        if kind == "audio"
        else capabilities.supports_video_input
    )
    return value is True


def omitted_media_text(kind: MediaKind) -> str:
    # Never inline the payload: history may carry multi-megabyte data URIs.
    return (
        f"[{kind.capitalize()} attachment omitted: "
        f"the current model does not accept {kind} input.]"
    )


def resolve_media_capabilities(
    capabilities: ModelCapabilities, *, native: bool, default: bool
) -> ModelCapabilities:
    def resolve(value: bool | None) -> bool:
        if not native:
            return False
        return default if value is None else value

    audio = resolve(capabilities.supports_audio_input)
    video = resolve(capabilities.supports_video_input)
    if (
        audio is capabilities.supports_audio_input
        and video is capabilities.supports_video_input
    ):
        return capabilities
    return capabilities.model_copy(
        update={"supports_audio_input": audio, "supports_video_input": video}
    )
