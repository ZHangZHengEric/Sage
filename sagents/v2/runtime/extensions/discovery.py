"""Discover explicitly declared third-party extensions from Python packages."""

from __future__ import annotations

from importlib import metadata

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions.contracts import ExtensionRegistration


ENTRY_POINT_GROUP = "sage.extensions"
SUPPORTED_EXTENSION_API_VERSION = "2"


def load_installed_extension(plugin_id: str) -> ExtensionRegistration:
    """Load one installed extension whose entry-point name is ``plugin_id``.

    Discovery is deliberately targeted: a package manifest must declare the
    plugin before its Python module is imported. Entry points must export an
    ``ExtensionRegistration`` object rather than an arbitrary module path or
    registration callback.
    """

    candidates = tuple(
        entry_point
        for entry_point in metadata.entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.name == plugin_id
    )
    if not candidates:
        raise _error(
            "extension.entry_point_not_found",
            ErrorCategory.VALIDATION,
            f"declared extension {plugin_id!r} is not installed in entry-point "
            f"group {ENTRY_POINT_GROUP!r}",
        )
    if len(candidates) > 1:
        raise _error(
            "extension.entry_point_ambiguous",
            ErrorCategory.CONFLICT,
            f"multiple installed distributions publish extension {plugin_id!r}",
        )

    try:
        registration = candidates[0].load()
    except Exception as exc:
        raise _error(
            "extension.entry_point_load_failed",
            ErrorCategory.PROVIDER_PERMANENT,
            f"failed to load declared extension {plugin_id!r}: "
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(registration, ExtensionRegistration):
        raise _error(
            "extension.entry_point_contract_invalid",
            ErrorCategory.VALIDATION,
            f"entry point {plugin_id!r} must export an ExtensionRegistration",
        )
    descriptor = registration.descriptor
    if descriptor.plugin_id != plugin_id:
        raise _error(
            "extension.entry_point_id_mismatch",
            ErrorCategory.CONFLICT,
            f"entry point {plugin_id!r} exported plugin {descriptor.plugin_id!r}",
        )
    if descriptor.api_version != SUPPORTED_EXTENSION_API_VERSION:
        raise _error(
            "extension.api_version_unsupported",
            ErrorCategory.UNSUPPORTED_SCHEMA,
            f"extension {plugin_id!r} requires API {descriptor.api_version!r}; "
            f"this runtime supports {SUPPORTED_EXTENSION_API_VERSION!r}",
        )
    return registration


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )
