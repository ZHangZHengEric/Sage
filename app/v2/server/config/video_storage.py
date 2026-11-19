"""Host-controlled S3 video storage grants for Server model routes."""

from collections.abc import Mapping
from typing import Any

from pydantic import Field, TypeAdapter

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.video_storage import S3VideoStorageConfig


class VideoStorageProfile(StrictModel):
    owner_ids: frozenset[str] = Field(min_length=1)
    storage: S3VideoStorageConfig


def parse_video_storage_profiles(value: str) -> dict[str, VideoStorageProfile]:
    return TypeAdapter(dict[str, VideoStorageProfile]).validate_json(value)


def authorize_video_storage(
    extra: Mapping[str, Any],
    owner_id: str,
    profiles: Mapping[str, VideoStorageProfile],
) -> S3VideoStorageConfig | None:
    if "video_storage" not in extra and "video_storage_profile" not in extra:
        return None
    name = extra.get("video_storage_profile")
    profile = profiles.get(name) if isinstance(name, str) else None
    if "video_storage" in extra or profile is None or owner_id not in profile.owner_ids:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.model_video_storage_forbidden",
            category=ErrorCategory.AUTHORIZATION,
            message="Choose a Server video storage profile authorized for this model owner.",
        ))
    return profile.storage
