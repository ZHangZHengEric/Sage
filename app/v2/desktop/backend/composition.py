"""Build Desktop's process Application through ``SAgentBuilder`` only."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
)
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.model import ModelProvider
from sagents.v2.runtime.session import DerivedStateStore, SessionStore
from sagents.v2.runtime.session.plugins import session_storage_providers

from app.v2.desktop.backend.bindings import DesktopExecutionBindingProvider
from app.v2.desktop.backend.package import desktop_v2_manifest
from app.v2.desktop.backend.runtime_config import _sandbox_network_policy


async def build_desktop_application(
    *,
    session_root: str | Path,
    workspace: str | Path,
    model_provider: ModelProvider | None = None,
    observability=None,
    session_store: SessionStore | None = None,
    derived_state_store: DerivedStateStore | None = None,
    component_selections: Mapping[str, str] | None = None,
    component_configs: Mapping[str, Mapping[str, Any]] | None = None,
    language: str = "en",
    bindings: DesktopExecutionBindingProvider | None = None,
    extensions: tuple[ExtensionRegistration, ...] = (),
    runtime: RuntimeConfig | dict | None = None,
    defer_recovery: bool = False,
) -> SAgentApplication:
    """Assemble Desktop runtime as Manifest + host bindings.

    Catalog, session index, and MCP records are not composition inputs.
    """

    root = Path(session_root).expanduser().resolve()
    workspace_path = Path(workspace).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    from app.v2.desktop.backend.revision_store import DesktopAgentRevisionStore
    builder = SAgentBuilder(revision_store=DesktopAgentRevisionStore(root))
    choices = {}
    def register_service(capability, value, *, ownership: Literal["owned", "borrowed"] = "borrowed"):
        plugin_id = "com.sage.desktop." + capability.replace(".", "-")
        ports = {capability: value}
        if capability == "session.store":
            ports = session_storage_providers(value)
            if derived_state_store is not None or not all(callable(getattr(value, key, None)) for key in (
                "get_derived_state", "put_derived_state", "delete_derived_state",
            )):
                ports.pop("derived-state.store")
        builder.register(ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id=plugin_id, name=capability, version="2.0.0",
                provides=tuple(CapabilityOffer(capability=key, api_version="2") for key in ports),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={"type": "object", "additionalProperties": False},
            ), factory=lambda context, deps: value, ownership=ownership,
            start=(lambda instance, context, deps: ports)
            if capability in {"session.store", "derived-state.store"} else None,
        ))
        choices[capability] = CapabilitySelection(plugin=plugin_id, scope=ExtensionScope.PROCESS)

    if model_provider is not None:
        register_service("model.provider", model_provider)
    if bindings is not None:
        register_service("execution.binding", bindings)
    else:
        choices["execution.binding"] = CapabilitySelection(
            plugin="sage.execution.binding.local-workspace",
            config={"workspace": str(workspace_path),
                    "private_workspace_root": str(root / "private-workspaces"),
                    "policy": {"network": _sandbox_network_policy(
                        (component_configs or {}).get("execution.sandbox", {}).get("network")
                    ).model_dump(mode="json")}},
        )
    for registration in extensions:
        builder.register(registration)
    for capability, value in (
        ("session.store", session_store), ("derived-state.store", derived_state_store),
        ("observability.provider", observability),
    ):
        if value is not None:
            register_service(capability, value)
    manifest = desktop_v2_manifest(
        session_root=root,
        component_selections=component_selections,
        component_configs=component_configs,
        language=language,
    )
    supplied = RuntimeConfig.model_validate(runtime) if runtime is not None else None
    effective = supplied or manifest.runtime
    effective = effective.model_copy(update={
        "capabilities": {**manifest.runtime.capabilities, **choices, **(supplied.capabilities if supplied else {})},
        "start_workers": not defer_recovery,
        "state_root": str(root),
    })
    application = await builder.build(runtime=effective)
    return application
