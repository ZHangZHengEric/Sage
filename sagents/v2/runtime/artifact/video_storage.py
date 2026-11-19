"""Session-owned private video copies in S3-compatible object storage."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Collection
from contextlib import ExitStack, closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from urllib.parse import urlsplit
from uuid import uuid4

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
    required = frozenset(required)
    prefix = _copy_prefix(config, run_id)
    # Client setup, decoding and read-only checks cannot create a copy. Keep
    # the client alive across preparation and upload, even on cancellation.
    with ExitStack() as resources:
        plan = await _settle_object_operation(partial(
            _prepare_upload, config, prefix, videos, required, resources
        ))
        if plan is None:
            return {}
        client, copies = plan
        available = {}
        for uri, copy in copies.items():
            if copy.payload is not None:
                try:
                    await _publish_video_copy(config, run_id, client, copy, store, dispatch)
                except SageV2Error:
                    if uri in required:
                        raise
                    continue
            available[uri] = copy.key
        return await _settle_object_operation(
            partial(_sign_video_urls, client, config, available, required)
        )


def video_copy_outcome_id(receipt_id: str) -> str:
    return receipt_id + "-outcome"


def video_copy_outcome(receipt_id: str, outcome: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=video_copy_outcome_id(receipt_id),
        media_type="application/x-sage-video-copy-outcome",
        size_bytes=0,
        digest="sha256:" + hashlib.sha256(b"").hexdigest(),
        metadata={"outcome": outcome},
    )


async def _empty():
    yield b""


async def _publish_video_copy(config, run_id, client, copy, store, dispatch):
    endpoint = str(config.endpoint_url or "").rstrip("/")
    identity = hashlib.sha256(f"{endpoint}\0{config.bucket}\0{copy.key}".encode()).hexdigest()
    receipt_id = VIDEO_COPY_RECEIPT_PREFIX + identity
    try:
        await store.put(
            artifact_id=receipt_id,
            media_type="application/x-sage-video-copy",
            content=_empty(),
            metadata={
                "run_id": run_id,
                "storage": config.model_dump(mode="json"),
                "key": copy.key,
                # A different caller may inspect an earlier attempt, but must
                # not use its receipt to submit another PUT for this key.
                "attempt": uuid4().hex,
            },
        )
    except SageV2Error as exc:
        if exc.info.code == "artifact.id_conflict":
            raise _storage_error("A prior video upload for this key requires reconciliation.") from None
        raise _storage_error("Could not record ownership of the video copy.", retryable=True) from None
    except OSError:
        raise _storage_error("Could not record ownership of the video copy.", retryable=True) from None

    attempt = _VideoWriteAttempt()

    async def upload():
        return await _settle_object_operation(
            partial(_put_video_copy, client, config, copy, attempt)
        )

    try:
        await dispatch(upload)
    finally:
        if attempt.outcome is not None:
            outcome = video_copy_outcome(receipt_id, attempt.outcome)
            await _settle(store.put(
                artifact_id=outcome.artifact_id,
                media_type=outcome.media_type,
                content=_empty(),
                metadata=outcome.metadata,
            ))


async def _settle_object_operation(operation):
    # Cancellation must keep the owning Session lock until the worker returns.
    async with auxiliary_capacity("model-media"):
        return await _settle(asyncio.to_thread(operation))


async def _settle(operation):
    task = asyncio.create_task(operation)
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
            # A timed-out PUT can still complete remotely. Never submit it again.
            retries={"mode": "standard", "total_max_attempts": 1},
        ),
    )


@dataclass(frozen=True, slots=True)
class _VideoCopy:
    key: str
    mime_type: str
    payload: bytes | None  # Existing objects only need a fresh signature.


def _storage_failure(exc):
    from botocore.exceptions import ClientError, ConnectionError, HTTPClientError

    if isinstance(exc, SageV2Error):
        return exc
    if isinstance(exc, ClientError):
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0
        return _storage_error(
            "Could not access the configured video object storage.",
            retryable=status in {409, 429} or status >= 500,
        )
    if isinstance(exc, (ConnectionError, HTTPClientError)):
        return _storage_error("Could not reach video object storage.", retryable=True)
    return _storage_error("Could not use the configured video object storage.")


def _prepare_upload(config, prefix, videos, required, resources):
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        client = resources.enter_context(closing(_client(config)))
    except (ClientError, BotoCoreError) as exc:
        if required.intersection(videos):
            raise _storage_failure(exc) from None
        return None

    copies = {}
    pending = set()
    for uri, mime_type in videos.items():
        try:
            payload = _decode_video(uri, mime_type)
            key = _object_key(prefix, payload, mime_type)
            try:
                client.head_object(Bucket=config.bucket, Key=key)
            except ClientError as error:
                status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if status not in {403, 404}:
                    raise
                pending.add(uri)
            else:
                payload = None
            copies[uri] = _VideoCopy(key, mime_type, payload)
        except (SageV2Error, ClientError, BotoCoreError) as exc:
            if uri in required:
                raise _storage_failure(exc) from None

    if pending:
        # Verify the exact cleanup scope can be listed before arming a
        # receipt or issuing a PUT. An inaccessible bucket must not make
        # its Session undeletable without ever storing any bytes.
        try:
            client.list_object_versions(Bucket=config.bucket, Prefix=prefix, MaxKeys=1)
            client.list_objects_v2(Bucket=config.bucket, Prefix=prefix, MaxKeys=1)
        except (ClientError, BotoCoreError) as exc:
            if required.intersection(pending):
                raise _storage_failure(exc) from None
            copies = {uri: copy for uri, copy in copies.items() if uri not in pending}
    return (client, copies) if copies else None


@dataclass(slots=True)
class _VideoWriteAttempt:
    # Until the worker starts, no request can have been sent.
    outcome: str | None = "not_written"


def _put_video_copy(client, config, copy, attempt) -> None:
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        NoCredentialsError,
        ParamValidationError,
        PartialCredentialsError,
    )

    attempt.outcome = None
    try:
        client.put_object(
            Bucket=config.bucket, Key=copy.key, Body=copy.payload,
            ContentType=copy.mime_type, IfNoneMatch="*",
        )
    except (NoCredentialsError, PartialCredentialsError, ParamValidationError) as exc:
        attempt.outcome = "not_written"
        raise _storage_failure(exc) from None
    except ClientError as exc:
        response = exc.response
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 412:
            attempt.outcome = "committed"
            return
        if response.get("Error", {}).get("Code") in {
            "AccessDenied", "ExpiredToken", "InvalidAccessKeyId", "InvalidArgument",
            "InvalidRequest", "InvalidToken", "NoSuchBucket", "SignatureDoesNotMatch",
        }:
            attempt.outcome = "not_written"
            raise _storage_failure(exc) from None
        raise _storage_error("Video upload outcome is unresolved.") from None
    except BotoCoreError:
        raise _storage_error("Video upload outcome is unresolved.") from None
    attempt.outcome = "committed"


def _sign_video_urls(client, config, uploaded, required) -> dict[str, str]:
    from botocore.exceptions import BotoCoreError, ClientError

    # Give every video its full TTL after all uploads finish.
    urls = {}
    for uri, key in uploaded.items():
        try:
            url = client.generate_presigned_url(
                "get_object", Params={"Bucket": config.bucket, "Key": key},
                ExpiresIn=config.url_ttl_seconds,
            )
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or not parsed.query:
                raise _storage_error("Video storage did not return a signed HTTPS URL.")
            urls[uri] = url
        except (SageV2Error, ClientError, BotoCoreError) as exc:
            if uri in required:
                raise _storage_failure(exc) from None
    return urls


async def confirm_video_copy(receipt: ArtifactRef) -> None:
    """Resolve an uncertain PUT only when its exact object is visible."""
    config = S3VideoStorageConfig.model_validate(receipt.metadata["storage"])
    key = receipt.metadata.get("key")
    if not key:
        raise SageV2Error(RuntimeErrorInfo(
            code="session.video_upload_unresolved",
            category=ErrorCategory.CONFLICT,
            message="This preview video receipt has no object-level outcome. Storage reconciliation is required.",
        ))
    prefix = _copy_prefix(config, receipt.metadata["run_id"])
    try:
        if key.startswith(prefix) and await _settle_object_operation(
            partial(_video_copy_exists, config, key)
        ):
            return
    except Exception:
        pass
    raise SageV2Error(RuntimeErrorInfo(
        code="session.video_upload_unresolved",
        category=ErrorCategory.PROVIDER_TRANSIENT,
        message="A video upload may still complete. Retry Session deletion after storage settles.",
        retryable=True,
    )) from None


def _video_copy_exists(config: S3VideoStorageConfig, key: str) -> bool:
    # A current delete marker can hide a committed version, so inspect versions.
    with closing(_client(config)) as client:
        versions = client.list_object_versions(Bucket=config.bucket, Prefix=key, MaxKeys=1000)
        if any(item["Key"] == key for item in versions.get("Versions", ())):
            return True
        objects = client.list_objects_v2(Bucket=config.bucket, Prefix=key, MaxKeys=1000)
        return any(item["Key"] == key for item in objects.get("Contents", ()))


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
