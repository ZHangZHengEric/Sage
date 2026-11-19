"""Session-owned private video copies in S3-compatible object storage."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Collection
from contextlib import closing, contextmanager
from contextvars import ContextVar
from functools import partial
from urllib.parse import urlsplit

from anyio import CancelScope
from pydantic import AnyHttpUrl, Field, field_validator

from sagents.v2.concurrency import auxiliary_capacity
from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.contracts import ArtifactRef


VIDEO_COPY_RECEIPT_PREFIX = "internal-video-copy-"
_video_owner = ContextVar("video_copy_owner", default=None)


@contextmanager
def bind_video_copy_owner(run_id, artifact_store, dispatch):
    token = _video_owner.set((run_id, artifact_store, dispatch))
    try:
        yield
    finally:
        _video_owner.reset(token)


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


def _copy_prefix(config: S3VideoStorageConfig, run_id: str) -> str:
    namespace = hashlib.sha256(run_id.encode()).hexdigest()
    return "/".join(filter(None, (config.prefix.strip("/"), "runs", namespace))) + "/"


def _object_key(prefix: str, payload: bytes, mime_type: str) -> str:
    digest = hashlib.sha256(mime_type.encode() + b"\0")
    digest.update(payload)
    suffix = {
        "video/mp4": "mp4", "video/mpeg": "mpeg", "video/quicktime": "mov",
        "video/mov": "mov", "video/avi": "avi", "video/x-flv": "flv",
        "video/webm": "webm", "video/wmv": "wmv", "video/3gpp": "3gp",
    }.get(mime_type, "video")
    return f"{prefix}{digest.hexdigest()}.{suffix}"


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
    try:
        import boto3  # noqa: F401
    except ImportError:
        if set(required).intersection(videos):
            raise _storage_error("Install sage[s3-video] to use model video storage.") from None
        return {}
    owner = _video_owner.get()
    if owner is None:
        if set(required).intersection(videos):
            raise _storage_error("Video storage requires a Session-owned model request.")
        return {}
    run_id, store, dispatch = owner
    serialized = config.model_dump_json()
    identity = hashlib.sha256(f"{run_id}\0{serialized}".encode()).hexdigest()

    async def empty_receipt():
        # The receipt is small metadata; no media is duplicated here.
        yield b""

    try:
        await store.put(
            artifact_id=VIDEO_COPY_RECEIPT_PREFIX + identity,
            media_type="application/x-sage-video-copy",
            content=empty_receipt(),
            metadata={"run_id": run_id, "storage": config.model_dump(mode="json")},
        )
    except (SageV2Error, OSError):
        if set(required).intersection(videos):
            raise _storage_error("Could not record ownership of the video copy.", retryable=True) from None
        return {}
    async def upload():
        return await _settle_object_operation(partial(
            _upload_and_sign, config, _copy_prefix(config, run_id), videos, frozenset(required)
        ))

    return await dispatch(upload)


async def _settle_object_operation(operation):
    # A Run cannot become terminal while its upload worker can still publish.
    # Likewise, Session deletion must retain its locks until cleanup settles.
    async with auxiliary_capacity("model-media"):
        task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
            if not task.cancelled():
                task.exception()
            raise


def _client(config: S3VideoStorageConfig):
    import boto3
    from botocore.config import Config

    return boto3.session.Session().client(
        "s3",
        region_name=config.region,
        endpoint_url=str(config.endpoint_url) if config.endpoint_url else None,
        config=Config(
            signature_version="s3v4", connect_timeout=5, read_timeout=30,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )


def _upload_and_sign(
    config: S3VideoStorageConfig, prefix: str, videos: dict[str, str], required: frozenset[str],
) -> dict[str, str]:
    def give_up(error: SageV2Error) -> dict[str, str]:
        if required.intersection(videos):
            raise error
        return {}

    from botocore.exceptions import BotoCoreError, ClientError, ConnectionError, HTTPClientError

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
        key = _object_key(prefix, payload, mime_type)
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
        with closing(_client(config)) as client:
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


async def delete_video_copies(receipt: ArtifactRef) -> None:
    """Purge this Run's versions while the owning Session is still durable."""
    config = S3VideoStorageConfig.model_validate(receipt.metadata["storage"])
    prefix = _copy_prefix(config, receipt.metadata["run_id"])
    try:
        await _settle_object_operation(partial(_delete_prefix, config, prefix))
    except Exception:
        raise SageV2Error(RuntimeErrorInfo(
            code="session.video_cleanup_failed",
            category=ErrorCategory.PROVIDER_TRANSIENT,
            message="Could not remove hosted video copies. Retry Session deletion.",
            retryable=True,
        )) from None


def _delete_prefix(config: S3VideoStorageConfig, prefix: str) -> None:
    with closing(_client(config)) as client:
        # Delete versions and delete markers too. A key-only delete in a
        # versioned bucket would leave the original video bytes behind.
        _delete_batches(
            client, config.bucket, prefix, client.list_object_versions,
            ("Versions", "DeleteMarkers"), versioned=True,
        )
        _delete_batches(
            client, config.bucket, prefix, client.list_objects_v2,
            ("Contents",), versioned=False,
        )


def _delete_batches(client, bucket, prefix, list_objects, fields, *, versioned):
    previous = None
    while True:
        # Read the first page after each deletion so removal cannot invalidate
        # the pagination cursor. This also verifies that the prefix is empty.
        page = list_objects(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
        objects = [
            {key: item[key] for key in ("Key", "VersionId")}
            if versioned else {"Key": item["Key"]}
            for field in fields
            for item in page.get(field, ())
        ]
        if not objects:
            if page.get("IsTruncated"):
                raise ValueError("Hosted video listing was incomplete.")
            return
        identities = frozenset((obj["Key"], obj.get("VersionId")) for obj in objects)
        if identities == previous or any(not obj["Key"].startswith(prefix) for obj in objects):
            raise ValueError("Hosted video cleanup could not safely advance.")
        response = client.delete_objects(
            Bucket=bucket, Delete={"Objects": objects, "Quiet": True}
        )
        if response.get("Errors"):
            raise ValueError("One or more hosted video copies could not be deleted.")
        previous = identities
