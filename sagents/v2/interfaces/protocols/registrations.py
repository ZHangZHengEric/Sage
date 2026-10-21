"""Official native and transport protocol adapter registrations."""

from __future__ import annotations

from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.interfaces.protocols.acp import AcpProtocolAdapter
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.interfaces.protocols.mcp import McpProtocolAdapter
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter
from sagents.v2.runtime.extensions.contracts import ExtensionScope
from sagents.v2.runtime.extensions.registration import (
    empty_config_schema,
    register_plugin,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_protocol_plugins(registry: ExtensionRegistry) -> None:
    for adapter, config_schema in (
        (NativeProtocolAdapter, empty_config_schema()),
        (
            AgUiProtocolAdapter,
            {
                "type": "object",
                "properties": {"enable_sage_extensions": {"type": "boolean"}},
                "additionalProperties": False,
            },
        ),
        (AcpProtocolAdapter, empty_config_schema()),
        (A2AProtocolAdapter, empty_config_schema()),
        (McpProtocolAdapter, empty_config_schema()),
    ):
        register_plugin(
            registry,
            adapter,
            "interface.protocol-adapter",
            lambda context, dependencies, adapter=adapter: adapter(**context.config),
            scopes={ExtensionScope.PROCESS, ExtensionScope.RUN},
            provider_name=adapter.plugin_id.rsplit(".", 1)[-1],
            multi_provider=True,
            config_schema=config_schema,
        )
