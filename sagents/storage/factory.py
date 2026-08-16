"""Configuration-driven construction of session storage backends."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Union

from sagents.storage.base import SessionStore, StorageError


SESSION_STORAGE_BACKEND_ENV = "SAGE_SESSION_STORAGE_BACKEND"
SESSION_STORAGE_OPTIONS_ENV = "SAGE_SESSION_STORAGE_OPTIONS"


@dataclass(frozen=True)
class SessionStorageConfig:
    """Backend-neutral configuration accepted by the public factory."""

    backend: str = "filesystem"
    options: Mapping[str, Any] = field(default_factory=dict)


SessionStorageConfigInput = Optional[
    Union[SessionStorageConfig, Mapping[str, Any], str]
]


def _environment_config() -> SessionStorageConfig:
    backend = os.environ.get(SESSION_STORAGE_BACKEND_ENV, "filesystem")
    raw_options = os.environ.get(SESSION_STORAGE_OPTIONS_ENV, "").strip()
    options: Mapping[str, Any] = {}
    if raw_options:
        try:
            parsed = json.loads(raw_options)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"{SESSION_STORAGE_OPTIONS_ENV} must contain a JSON object"
            ) from exc
        if not isinstance(parsed, dict):
            raise StorageError(
                f"{SESSION_STORAGE_OPTIONS_ENV} must contain a JSON object"
            )
        options = parsed
    return SessionStorageConfig(backend=backend, options=options)


def normalize_session_storage_config(
    config: SessionStorageConfigInput = None,
    *,
    session_root: Optional[str] = None,
) -> SessionStorageConfig:
    if config is None:
        normalized = _environment_config()
    elif isinstance(config, SessionStorageConfig):
        normalized = config
    elif isinstance(config, str):
        normalized = SessionStorageConfig(backend=config)
    elif isinstance(config, Mapping):
        backend = str(config.get("backend") or "filesystem")
        raw_options = config.get("options") or {}
        if not isinstance(raw_options, Mapping):
            raise StorageError("session storage options must be a mapping")
        normalized = SessionStorageConfig(backend=backend, options=dict(raw_options))
    else:
        raise StorageError(
            f"unsupported session storage config type: {type(config).__name__}"
        )

    options = dict(normalized.options)
    if session_root and "root" not in options:
        options["root"] = session_root
    return SessionStorageConfig(
        backend=normalized.backend.strip().lower(),
        options=options,
    )


def create_session_store(
    config: SessionStorageConfigInput = None,
    *,
    session_root: Optional[str] = None,
    initialize: bool = True,
) -> SessionStore:
    """Create the configured backend without exposing implementation classes."""

    normalized = normalize_session_storage_config(
        config, session_root=session_root
    )
    if normalized.backend == "filesystem":
        from sagents.storage.filesystem import _FilesystemSessionStore

        root = normalized.options.get("root")
        if not root:
            raise StorageError("filesystem session storage requires options.root")
        unknown = set(normalized.options) - {"root"}
        if unknown:
            names = ", ".join(sorted(unknown))
            raise StorageError(f"unknown filesystem storage options: {names}")
        return _FilesystemSessionStore(
            str(root), auto_initialize=initialize
        )

    raise StorageError(
        f"unsupported session storage backend: {normalized.backend!r}"
    )
