"""Manifest resolution and plugin selection rules shared by assembly paths."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.resolver import (
    CompositionResolver,
    ResolvedSageManifest,
)
from sagents.v2.package.manifest.root import PluginDeclaration, SageManifest
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.runtime.extensions import (
    ExtensionRegistry,
)


def _validate_declared_plugin_trust(
    extensions: ExtensionRegistry,
    declarations: tuple[PluginDeclaration, ...],
    *,
    built_in_only: bool,
) -> None:
    if not built_in_only:
        return
    for declaration in declarations:
        if extensions.contains(declaration.id) and extensions.is_trusted_builtin(
            declaration.id
        ):
            continue
        raise SageV2Error(
            RuntimeErrorInfo(
                code="extension.plugin_trust_policy_violation",
                category=ErrorCategory.VALIDATION,
                message=(
                    "built_in_only policy rejected declared extension "
                    f"{declaration.id!r} before loading its entry point"
                ),
                safe_to_resume=False,
                metadata={
                    "plugin_id": declaration.id,
                    "plugin_trust_policy": "built_in_only",
                },
            )
        )


def _resolve_package(package, *, runtime: RuntimeConfig | None = None, models=None):
    if isinstance(package, ResolvedSageManifest):
        if runtime is not None and runtime != package.runtime:
            raise ValueError("cannot override runtime on an already resolved package; configure before resolution")
        # Frozen models can still contain mutable dictionaries. Keep the
        # application's policy and child defaults independent of the host.
        return None, package.model_copy(deep=True)
    if isinstance(package, (str, Path)):
        package = SageManifestLoader().load(package)
    if not isinstance(package, SageManifest):
        raise TypeError(
            "package must be SageManifest, ResolvedSageManifest, or sage.yaml"
        )
    if runtime is not None:
        package = package.model_copy(update={"runtime": runtime.model_copy(deep=True)})
    return package, CompositionResolver().resolve(package, models=models)


def _merge_plugin_config(
    declarations: tuple[PluginDeclaration, ...],
    plugin_id: str,
    selection_config: dict[str, Any],
) -> dict[str, Any]:
    defaults = next(
        (
            declaration.config
            for declaration in declarations
            if declaration.id == plugin_id
        ),
        {},
    )
    return {**defaults, **selection_config}


def _supported_locked_config(
    extensions: ExtensionRegistry,
    plugin_id: str,
    locked_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Inject host-owned values only when the selected plugin declares them."""

    if not extensions.is_trusted_builtin(plugin_id):
        return {}
    schema = extensions.get(plugin_id).descriptor.config_schema or {}
    if schema.get("additionalProperties", True) is not False:
        return dict(locked_config)
    properties = set((schema.get("properties") or {}).keys())
    return {key: value for key, value in locked_config.items() if key in properties}


def _selection(runtime: RuntimeConfig, capability: str) -> CapabilitySelection | None:
    values = runtime.selections(capability)
    if len(values) > 1 and capability != "tool.catalog":
        raise ValueError(
            f"capability {capability!r} does not allow multiple selections here"
        )
    return values[0] if values else None
