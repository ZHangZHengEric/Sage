"""SAgents V2 module for interfaces/protocols/native.py."""

from __future__ import annotations

from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.interfaces.protocols.contracts import (
    AdapterCapabilities,
    AdapterResult,
    frame,
)


class NativeProtocolAdapter:
    plugin_id = "sage.protocol.native"
    name = "Native protocol adapter"
    description = "Exposes the native Sage event stream without protocol translation."

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            protocol="sage-native",
            protocol_version="2",
            adapter_version="1",
            supports_run_lifecycle=True,
            supports_item_lifecycle=True,
            supports_reasoning=True,
            supports_tool_lifecycle=True,
            supports_interactions=True,
            supports_pause_resume=True,
            supports_exact_cursor_replay=True,
            supports_flow=True,
            supports_artifacts=True,
        )

    def translate(self, event: RuntimeEvent) -> AdapterResult:
        return AdapterResult(
            frames=(
                frame(
                    event,
                    protocol="sage-native",
                    version="2",
                    name=event.type,
                    payload=event.model_dump(mode="json"),
                ),
            )
        )
