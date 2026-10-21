"""Official sandbox provider registrations and configuration schemas."""

from __future__ import annotations

import importlib.util

from sagents.v2.runtime.execution.sandbox import (
    CubeVolumeSandboxProvider,
    InMemorySandboxProvider,
    LocalWorkspaceSandboxProvider,
)
from sagents.v2.runtime.extensions.contracts import (
    ExtensionAvailability,
    ExtensionDependency,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import register_plugin
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_sandbox_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        InMemorySandboxProvider,
        "execution.sandbox",
        lambda context, dependencies: InMemorySandboxProvider(
            _bytes(context.config["verification_key"]),
            process_handlers=dependencies.get_provider(
                "execution.sandbox.process-handlers"
            ),
            network_handlers=dependencies.get_provider(
                "execution.sandbox.network-handlers"
            ),
            terminal_ttl_seconds=int(
                context.config.get("terminal_ttl_seconds", 86_400)
            ),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 1024)
            ),
        ),
        dependencies=(
            ExtensionDependency(
                capability="execution.sandbox.process-handlers",
                name="default",
                optional=True,
            ),
            ExtensionDependency(
                capability="execution.sandbox.network-handlers",
                name="default",
                optional=True,
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        api_version="3",
        version="3.0.0",
        config_schema=_sandbox_config_schema(in_memory=True),
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )

    register_plugin(
        registry,
        LocalWorkspaceSandboxProvider,
        "execution.sandbox",
        lambda context, dependencies: LocalWorkspaceSandboxProvider(
            _bytes(context.config["verification_key"]),
            **{
                key: context.config[key]
                for key in (
                    "command_path",
                    "read_paths",
                    "linux_cgroup_root",
                    "linux_quota_mount",
                    "linux_execution_uid",
                    "linux_execution_gid",
                )
                if key in context.config
            },
            terminal_ttl_seconds=int(
                context.config.get("terminal_ttl_seconds", 86_400)
            ),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 1024)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        api_version="3",
        version="3.0.0",
        config_schema=_sandbox_config_schema(in_memory=False),
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )

    register_plugin(
        registry,
        CubeVolumeSandboxProvider,
        "execution.sandbox",
        lambda context, dependencies: CubeVolumeSandboxProvider(
            _bytes(context.config["verification_key"]),
            api_url=context.config["api_url"],
            template_id=context.config["template_id"],
            proxy_node_ip=context.config["proxy_node_ip"],
            api_key=context.config.get("api_key"),
            volume_driver=context.config.get("volume_driver"),
        ),
        scopes={ExtensionScope.PROCESS},
        api_version="3",
        version="3.0.0",
        availability=ExtensionAvailability(
            available=importlib.util.find_spec("cubesandbox") is not None,
            reason=(
                None
                if importlib.util.find_spec("cubesandbox") is not None
                else "optional cubesandbox>=0.6.0 package is not installed"
            ),
        ),
        config_schema={
            "type": "object",
            "properties": {
                "verification_key": {},
                "api_url": {"type": "string", "minLength": 1},
                "template_id": {"type": "string", "minLength": 1},
                "proxy_node_ip": {"type": "string", "minLength": 1},
                "api_key": {"type": "string", "writeOnly": True},
                "volume_driver": {"type": "string"},
            },
            "required": ["verification_key", "api_url", "template_id", "proxy_node_ip"],
            "additionalProperties": False,
        },
        capabilities={"supports_terminal_purge": True},
    )


def _sandbox_config_schema(*, in_memory: bool) -> dict:
    properties = {
        "verification_key": {},
        "terminal_ttl_seconds": {"type": "integer", "minimum": 1},
        "max_retained_terminal_items": {"type": "integer", "minimum": 0},
    }
    if not in_memory:
        properties.update(
            {
                "network": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["none", "unrestricted", "allowlist", "proxy"],
                        },
                        "deny_private_networks": {"type": "boolean"},
                        "allowed_hosts": {"type": "array", "items": {"type": "string"}},
                        "allowed_ports": {
                            "type": "array",
                            "items": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 65535,
                            },
                        },
                        "allowed_schemes": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["http", "https"]},
                        },
                        "proxy_url": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "command_path": {"type": "string", "minLength": 1},
                "read_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "linux_cgroup_root": {"type": "string"},
                "linux_quota_mount": {"type": "string"},
                "linux_execution_uid": {"type": "integer", "minimum": 1},
                "linux_execution_gid": {"type": "integer", "minimum": 1},
            }
        )
    if in_memory:
        properties.update({})
    return {
        "type": "object",
        "properties": properties,
        "required": ["verification_key"],
        "additionalProperties": False,
    }


def _bytes(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()
