"""Video payload helpers shared by model wire adapters."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.runtime.artifact.video_storage import (
    S3VideoStorageConfig as S3VideoStorageConfig,
    publish_videos as publish_videos,
)


STORAGE_OMITTED_TEXT = (
    "[Video omitted from this model request because video storage is unavailable.]"
)


def current_turn_start(roles: Sequence[str], model_role: str) -> int:
    """Index of the first message after the latest model reply."""
    for index in range(len(roles) - 1, -1, -1):
        if roles[index] == model_role:
            return index + 1
    return 0


def redact_signed_urls(value: Any, signed_urls: Collection[str]) -> Any:
    if not signed_urls:
        return value
    if isinstance(value, str):
        for url in signed_urls:
            value = value.replace(url, url.partition("?")[0] + "?[redacted]")
        return value
    if isinstance(value, dict):
        return {key: redact_signed_urls(item, signed_urls) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_signed_urls(item, signed_urls) for item in value]
    return value


def redact_error_info(info: RuntimeErrorInfo, signed_urls: Collection[str]) -> RuntimeErrorInfo:
    if not signed_urls:
        return info
    return RuntimeErrorInfo.model_validate(redact_signed_urls(info.model_dump(), signed_urls))
