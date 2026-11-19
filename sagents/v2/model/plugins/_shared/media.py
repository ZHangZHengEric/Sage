"""Audio/video block handling shared by model wire adapters."""

from __future__ import annotations

from typing import Literal

from sagents.v2.contracts.conversation import is_user_request
from sagents.v2.contracts.items import AudioBlock, FileBlock, TextBlock
from sagents.v2.model.contracts import ModelCapabilities, ModelMessage
from sagents.v2.runtime.artifact.workspace_images import materialize_inline_media

MediaKind = Literal["audio", "video"]


def media_kind(block: object) -> MediaKind | None:
    if isinstance(block, AudioBlock):
        return "audio"
    if isinstance(block, FileBlock) and block.mime_type:
        prefix = block.mime_type.split("/", 1)[0].lower()
        if prefix == "audio" or prefix == "video":
            return prefix
    return None


def omit_historical_remote_media(
    messages: tuple[ModelMessage, ...],
) -> tuple[ModelMessage, ...]:
    """Keep history intact while limiting remote media fetches to their turn."""
    last_reply = next(
        (index for index in range(len(messages) - 1, -1, -1)
         if messages[index].role == "assistant"),
        -1,
    )
    current_start = last_reply + 1
    user_indices = [
        index for index in range(current_start, len(messages))
        if is_user_request(messages[index])
    ]
    if user_indices:
        latest = user_indices[-1]
        source_run = messages[latest].metadata.get("source_run_id")
        if source_run is not None:
            # One Run can admit several adjacent user Items together.
            while (latest > current_start and is_user_request(messages[latest - 1])
                   and messages[latest - 1].metadata.get("source_run_id") == source_run):
                latest -= 1
        current_start = latest
    if current_start == 0:
        return messages
    history = []
    for message in messages[:current_start]:
        content = []
        for block in message.content:
            kind = media_kind(block)
            if kind and block.uri.lstrip()[:8].lower().startswith(("http://", "https://", "gs://")):
                block = TextBlock(
                    text=f"[Earlier {kind} attachment omitted from the model request.]"
                )
            content.append(block)
        history.append(
            message if tuple(content) == message.content
            else message.model_copy(update={"content": tuple(content)})
        )
    return (*history, *messages[current_start:])



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


async def media_reference_text(
    kind: MediaKind, mime_type: str, *, data: str | None = None, uri: str | None = None
) -> str:
    """Replace media that does not fit the request with a short text reference."""
    label = kind.capitalize()
    if data is None:
        return f"[{label} reference: {uri}]"
    path = await materialize_inline_media(data, mime_type.lower())
    if path:
        return f"[Workspace {kind}: {path}]"
    return f"[{label} omitted from this model request because of the request limits.]"


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
