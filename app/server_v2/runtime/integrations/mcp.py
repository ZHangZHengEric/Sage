from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

from app.server_v2.catalog.records import McpServerRecord
from app.server_v2.observability.logging import get_logger
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin

_LOGGER = get_logger(__name__)


def to_mcp_config(
    record: McpServerRecord, *, required: bool = False
) -> McpServerConfig:
    try:
        return McpServerConfig(
            name=record.name,
            protocol=record.protocol,
            url=record.url,
            api_key=record.api_key,
            required=required,
        )
    except Exception as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.runtime.integrations.mcp.validation",
                category=ErrorCategory.VALIDATION,
                message=f"invalid mcp {record.name}: {exc}",
            )
        ) from exc


async def discover_mcp_tools(config: McpServerConfig) -> list[str]:
    plugin = McpToolPlugin((config,))
    definitions = await plugin.list_tools(run_id="discover")
    errors = plugin.discovery_errors()
    if config.name in errors:
        info = errors[config.name]
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.runtime.integrations.mcp.validation",
                category=ErrorCategory.VALIDATION,
                message=info.message,
            )
        )
    return [item.name for item in definitions]


def mcp_server_configs(
    records: Iterable[McpServerRecord],
) -> tuple[McpServerConfig, ...]:
    """Project enabled records onto transport configs, skipping broken ones.

    A server is validated when it is saved, but a record can still become
    unusable later — a catalog written by an older build, or a transport this
    deployment no longer supports. Dropping it degrades to "that server has no
    Tools", which matches how an unreachable server already behaves; raising
    would fail the entire Run over one bad row.
    """

    configs: list[McpServerConfig] = []
    for item in records:
        if item.disabled:
            continue
        try:
            configs.append(to_mcp_config(item, required=False))
        except SageV2Error:
            _LOGGER.warning(
                "mcp.server.skipped", "skipping unusable mcp server", name=item.name
            )
    return tuple(configs)


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

    def invalidate(self, user_id: str) -> None:
        """Forget this user's plugins so the next Run rediscovers their Tools.

        A discovery result is cached for the lifetime of the entry, and the
        fingerprint covers only the transport — so a server that was down when
        it was first listed, or that has since gained Tools, would otherwise
        stay stale forever with no way for the tenant to recover.
        """

        for key in [item for item in self._plugins if item[0] == user_id]:
            self._plugins.pop(key, None)

    def clear(self) -> None:
        self._plugins.clear()
