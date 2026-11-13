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
        path = sandbox.filesystem.normalize_path(relative)
        try:
            existing = await sandbox.filesystem.read_bytes(path, **authorization("read", path=path))
        except FileNotFoundError:
            try:
                await sandbox.filesystem.write_bytes(
                    path, content, overwrite=False, **authorization("create", path=path),
                )
            except FileExistsError:
                existing = await sandbox.filesystem.read_bytes(path, **authorization("read", path=path))
            else:
                existing = content
        if existing != content:
            raise ValueError("Workspace image content does not match its reference.")
        return relative
    except (SageV2Error, OSError, ValueError, OverflowError) as exc:
        raise _unavailable("Could not store an image in the Run workspace.") from exc


def _unavailable(message: str) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="model.image_workspace_unavailable",
        category=ErrorCategory.VALIDATION,
        message=message,
        safe_to_resume=True,
    ))
