"""Materialize model image references through the active Run sandbox."""

from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.execution.sandbox.contracts import NetworkRequest, OperationIntent


_workspace = ContextVar("model_image_workspace", default=None)
_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp",
}
_IMAGE_DIRECTORY = ".sage-model-images"
_MEDIA_EXTENSIONS = {
    "video/mp4": ".mp4", "video/mpeg": ".mpeg", "video/mov": ".mov",
    "video/quicktime": ".mov", "video/avi": ".avi", "video/x-msvideo": ".avi",
    "video/x-flv": ".flv", "video/mpg": ".mpg", "video/webm": ".webm",
    "video/wmv": ".wmv", "video/x-ms-wmv": ".wmv", "video/3gpp": ".3gp",
    "audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/aac": ".aac",
    "audio/aiff": ".aiff", "audio/flac": ".flac", "audio/ogg": ".ogg",
    "audio/m4a": ".m4a", "audio/opus": ".opus",
}
_MEDIA_DIRECTORIES = {"video": ".sage-model-videos", "audio": ".sage-model-audio"}


def workspace_image_path(digest: str, extension: str) -> str:
    return f"{_IMAGE_DIRECTORY}/{digest}{extension}"


def minimum_workspace_image_path() -> str:
    return workspace_image_path("0" * 64, ".jpg")


@contextmanager
def bind_image_workspace(runtime):
    token = _workspace.set(runtime)
    try:
        yield
    finally:
        _workspace.reset(token)


async def materialize_image_source(source: dict) -> str:
    runtime = _workspace.get()
    if runtime is None:
        raise _unavailable("Image reference fallback requires a Run workspace.")
    sandbox = runtime.sandbox

    def authorization(operation, **target):
        intent = OperationIntent(
            operation=operation, run_id=sandbox.ref.owner_run_id,
            tool_call_id="model-image-reference", sandbox_id=sandbox.ref.sandbox_id,
            **target,
        )
        return {"intent": intent, "grant": runtime.grant_issuer.issue(
            ref=sandbox.ref, intent=intent, allowed_operations=frozenset({operation}),
        )}

    try:
        if source.get("type") == "base64":
            content = base64.b64decode(source["data"], validate=True)
            mime = source.get("media_type")
        else:
            url = source.get("url", "")
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Image source is not a supported URL.")
            response = await sandbox.network.request(
                NetworkRequest(url=url, timeout_seconds=15),
                **authorization("network.request", network_host=parsed.hostname,
                    network_port=parsed.port or (443 if parsed.scheme == "https" else 80)),
            )
            if not 200 <= response.status_code < 300 or response.truncated:
                raise ValueError("Image download did not complete.")
            content = response.body
            mime = next((value.partition(";")[0].strip().lower()
                         for key, value in response.headers.items() if key.lower() == "content-type"), None)
        extension = _EXTENSIONS.get(mime)
        if not content or extension is None:
            raise ValueError("Image data is missing or has an unsupported format.")
        digest = hashlib.sha256(content).hexdigest()
        relative = workspace_image_path(digest, extension)
        await _store_content(sandbox, relative, content, authorization)
        return relative
    except (SageV2Error, OSError, ValueError, OverflowError) as exc:
        raise _unavailable("Could not store an image in the Run workspace.") from exc


async def materialize_inline_media(data: str, mime_type: str) -> str | None:
    runtime = _workspace.get()
    directory = _MEDIA_DIRECTORIES.get(mime_type.partition("/")[0])
    if runtime is None or directory is None:
        return None
    sandbox = runtime.sandbox

    def authorization(operation, *, path):
        intent = OperationIntent(
            operation=operation, run_id=sandbox.ref.owner_run_id,
            tool_call_id="model-media-reference", sandbox_id=sandbox.ref.sandbox_id,
            path=path,
        )
        return {"intent": intent, "grant": runtime.grant_issuer.issue(
            ref=sandbox.ref, intent=intent, allowed_operations=frozenset({operation}),
        )}

    try:
        content = base64.b64decode(data, validate=True)
        digest = hashlib.sha256(content).hexdigest()
        extension = _MEDIA_EXTENSIONS.get(mime_type, ".bin")
        relative = f"{directory}/{digest}{extension}"
        await _store_content(sandbox, relative, content, authorization)
    except (SageV2Error, OSError, ValueError, OverflowError):
        return None
    return relative


async def _store_content(sandbox, relative, content, authorization):
    path = sandbox.filesystem.normalize_path(relative)
    try:
        existing = await sandbox.filesystem.read_bytes(path, **authorization("read", path=path))
    except FileNotFoundError:
        try:
            await sandbox.filesystem.write_bytes(
                path, content, overwrite=False, **authorization("create", path=path),
            )
            return
        except FileExistsError:
            existing = await sandbox.filesystem.read_bytes(path, **authorization("read", path=path))
    if existing != content:
        raise ValueError("Workspace file content does not match its reference.")


def _unavailable(message: str) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="model.image_workspace_unavailable",
        category=ErrorCategory.VALIDATION,
        message=message,
        safe_to_resume=True,
    ))
