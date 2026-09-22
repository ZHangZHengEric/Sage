from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import McpServerRecord


def to_mcp_config(record: McpServerRecord, *, required: bool = False) -> McpServerConfig:
    try:
        return McpServerConfig(
            name=record.name,
            protocol=record.protocol,  # type: ignore[arg-type]
            url=record.url,
            api_key=record.api_key,
            command=record.command,
            args=tuple(record.args),
            env=dict(record.env),
            required=required,
        )
    except Exception as exc:
        raise ServerV2Error("validation", f"invalid mcp {record.name}: {exc}") from exc


async def discover_mcp_tools(config: McpServerConfig) -> list[str]:
    plugin = McpToolPlugin((config,))
    definitions = await plugin.list_tools(run_id="discover")
    errors = plugin.discovery_errors()
    if config.name in errors:
        info = errors[config.name]
        raise ServerV2Error("validation", info.message)
    return [item.name for item in definitions]


def mcp_server_configs(
    records: Iterable[McpServerRecord],
) -> tuple[McpServerConfig, ...]:
    return tuple(
        to_mcp_config(item, required=False) for item in records if not item.disabled
    )


class McpPluginCache:
    """One MCP plugin per (user, server set), shared by every Run.

    Discovery is the expensive half of MCP — one session per server on every
    listing — and its result describes the server set, not a Run. A plugin
    built per Run can therefore never hit its own catalog cache. The plugin is
    already Run-aware: idempotency state is keyed by ``run_id`` and the engine
    calls ``release_run`` at terminal states, so one instance safely backs many
    Runs.

    Entries are keyed by the server fingerprint rather than replaced in place,
    so a Run still executing against the previous configuration keeps the
    plugin it was composed with. The map is bounded because it is keyed by
    user: eviction only costs a rediscovery.
    """

    def __init__(self, max_entries: int = 256) -> None:
        self._plugins: OrderedDict[tuple[str, str], McpToolPlugin] = OrderedDict()
        self._max_entries = max(1, max_entries)

    def get(
        self, user_id: str, records: Iterable[McpServerRecord]
    ) -> McpToolPlugin | None:
        servers = mcp_server_configs(records)
        if not servers:
            return None
        key = (user_id, McpToolPlugin.servers_fingerprint(servers))
        cached = self._plugins.get(key)
        if cached is not None:
            self._plugins.move_to_end(key)
            return cached
        plugin = McpToolPlugin(servers)
        self._plugins[key] = plugin
        while len(self._plugins) > self._max_entries:
            self._plugins.popitem(last=False)
        return plugin

    def clear(self) -> None:
        self._plugins.clear()
