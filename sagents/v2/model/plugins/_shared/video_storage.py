"""Private S3 uploads and short-lived URLs for model video inputs."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Collection, Sequence
from contextlib import closing
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, field_validator

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class S3VideoStorageConfig(StrictModel):
    bucket: str = Field(min_length=1)
    region: str | None = None
    endpoint_url: AnyHttpUrl | None = None
    prefix: str = "sage/model-video"
    url_ttl_seconds: int = Field(default=900, gt=0, le=3600)

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint(cls, value):
        if value is not None and (
            value.scheme != "https" or value.username or value.password
            or value.query or value.fragment
        ):
            raise ValueError("video storage requires an HTTPS endpoint without credentials")
        return value


STORAGE_OMITTED_TEXT = (
    "[Video omitted from this model request because video storage is unavailable.]"
)


def current_turn_start(roles: Sequence[str], model_role: str) -> int:
    """Index of the first message after the latest model reply."""
    for index in range(len(roles) - 1, -1, -1):
        if roles[index] == model_role:
            return index + 1
    return 0


def _storage_error(message: str, *, retryable: bool = False) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="model.video_storage_failed",
        category=ErrorCategory.PROVIDER_TRANSIENT if retryable else ErrorCategory.VALIDATION,
        message=message,
        retryable=retryable,
        safe_to_resume=True,
    ))


def _decode_video(uri: str, mime_type: str) -> bytes:
    header, separator, encoded = uri.partition(",")
    if not separator or header.lower() != f"data:{mime_type.lower()};base64":
        raise _storage_error("Expected a Base64 video matching the attachment MIME type.")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise _storage_error("Invalid Base64 video attachment.") from None
    if not payload:
        raise _storage_error("Video attachment is empty.")
    return payload


def _object_key(config: S3VideoStorageConfig, payload: bytes, mime_type: str) -> str:
    digest = hashlib.sha256(mime_type.encode() + b"\0")
    digest.update(payload)
    suffix = {
        "video/mp4": "mp4", "video/mpeg": "mpeg", "video/quicktime": "mov",
        "video/mov": "mov", "video/avi": "avi", "video/x-flv": "flv",
        "video/webm": "webm", "video/wmv": "wmv", "video/3gpp": "3gp",
    }.get(mime_type, "video")
    return "/".join(filter(None, (config.prefix.strip("/"), f"{digest.hexdigest()}.{suffix}")))


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


async def publish_videos(
    config: S3VideoStorageConfig,
    videos: dict[str, str],
    *,
    required: Collection[str] = (),
) -> dict[str, str]:
    """Return signed URLs keyed by data URI.

    A failed upload raises only for URIs in ``required``; other failed videos
    are left out of the result so the caller can omit them from the request.
    """
    if not videos:
        return {}
    return await bounded_to_thread(
        "model-media", partial(_upload_and_sign, config, videos, frozenset(required))
    )


def _upload_and_sign(
    config: S3VideoStorageConfig, videos: dict[str, str], required: frozenset[str],
) -> dict[str, str]:
    def give_up(error: SageV2Error) -> dict[str, str]:
        if required.intersection(videos):
            raise error
        return {}

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import (
            BotoCoreError,
            ClientError,
            ConnectionError,
            HTTPClientError,
        )
    except ImportError:
        return give_up(_storage_error("Install sage[s3-video] to use model video storage."))

    def translate(exc: SageV2Error | ClientError | BotoCoreError) -> SageV2Error:
        if isinstance(exc, SageV2Error):
            return exc
        if isinstance(exc, ClientError):
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0
            return _storage_error(
                "Could not upload the video to the configured object storage.",
                retryable=status in {409, 429} or status >= 500,
            )
        if isinstance(exc, (ConnectionError, HTTPClientError)):
            return _storage_error("Could not reach video object storage.", retryable=True)
        return _storage_error("Could not use the configured video object storage.")

    def store(client, uri: str, mime_type: str) -> str:
        payload = _decode_video(uri, mime_type)
        key = _object_key(config, payload, mime_type)
        try:
            client.head_object(Bucket=config.bucket, Key=key)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            # A missing key can return 403 when the principal has no ListBucket grant.
            if status not in {403, 404}:
                raise
            try:
                client.put_object(
                    Bucket=config.bucket, Key=key, Body=payload,
                    ContentType=mime_type, IfNoneMatch="*",
                )
            except ClientError as conflict:
                if conflict.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                    raise
        return key

    try:
        with closing(boto3.session.Session().client(
            "s3",
            region_name=config.region,
            endpoint_url=str(config.endpoint_url) if config.endpoint_url else None,
            config=Config(
                signature_version="s3v4", connect_timeout=5, read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 3},
            ),
        )) as client:
            keys = {}
            for uri, mime_type in videos.items():
                try:
                    keys[uri] = store(client, uri, mime_type)
                except (SageV2Error, ClientError, BotoCoreError) as exc:
                    if uri in required:
                        raise translate(exc) from None
            # Give every video the full TTL after all uploads have finished.
            urls = {
                uri: client.generate_presigned_url(
                    "get_object", Params={"Bucket": config.bucket, "Key": key},
                    ExpiresIn=config.url_ttl_seconds,
                )
                for uri, key in keys.items()
            }
    except SageV2Error:
        raise
    except (ClientError, BotoCoreError) as exc:
        return give_up(translate(exc))

    for uri, url in list(urls.items()):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.query:
            if uri in required:
                raise _storage_error("Video storage did not return a signed HTTPS URL.")
            del urls[uri]
    return urls
