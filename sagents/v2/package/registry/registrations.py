"""Official package registry registrations."""

from __future__ import annotations

from sagents.v2.package.registry import InMemoryAgentPackageRegistry
from sagents.v2.runtime.extensions.contracts import ExtensionDependency, ExtensionScope
from sagents.v2.runtime.extensions.registration import (
    empty_config_schema,
    register_plugin,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_package_registry_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        InMemoryAgentPackageRegistry,
        "package.registry",
        lambda context, dependencies: InMemoryAgentPackageRegistry(
            resolver=dependencies.require_unique("package.resolver")
        ),
        dependencies=(ExtensionDependency(capability="package.resolver"),),
        scopes={ExtensionScope.PROCESS},
        config_schema=empty_config_schema(),
        capabilities={
            "durable_across_process_restart": False,
            "supports_package_signatures": False,
            "shared_across_processes": False,
        },
    )
