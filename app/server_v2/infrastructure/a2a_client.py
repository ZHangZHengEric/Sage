from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable

from sagents.v2.tool.plugins.a2a import (
    MAX_CALL_DEPTH,
    A2AAgentConfig,
    A2AToolPlugin,
    A2ATransport,
)

from app.server_v2.core.errors import ServerError
from app.server_v2.domain.catalog import A2AAgentRecord

_LOGGER = logging.getLogger(__name__)


def to_a2a_config(record: A2AAgentRecord, *, required: bool = False) -> A2AAgentConfig:
    try:
        return A2AAgentConfig(
            name=record.name,
            url=record.url or "",
            api_key=record.api_key,
            required=required,
        )
    except Exception as exc:
        raise ServerError(
            "validation", f"invalid a2a agent {record.name}: {exc}"
        ) from exc


async def discover_a2a_skills(config: A2AAgentConfig) -> list[str]:
    plugin = A2AToolPlugin((config,))
    definitions = await plugin.list_tools(run_id="discover")
    errors = plugin.discovery_errors()
    if config.name in errors:
        raise ServerError("validation", errors[config.name].message)
    return [item.name for item in definitions]


def a2a_agent_configs(
    records: Iterable[A2AAgentRecord],
) -> tuple[A2AAgentConfig, ...]:
    """Project enabled records onto peer configs, skipping broken ones.

    Same degradation as the MCP bridge: one unusable row costs that peer's
    Tools, which is how an unreachable peer already behaves, rather than
    failing the entire Run.
    """

    configs: list[A2AAgentConfig] = []
    for item in records:
        if item.disabled:
            continue
        try:
            configs.append(to_a2a_config(item, required=False))
        except ServerError:
            _LOGGER.warning("skipping unusable a2a agent %r", item.name)
    return tuple(configs)


class A2APluginCache:
    """One A2A plugin per (user, hop depth, peer set), shared by every Run.

    Keyed like the MCP cache, for the same reason: Agent Card discovery
    describes the peer set rather than a Run, so a plugin built per Run could
    never hit its own cache.

    Depth is part of the key because it is part of what the plugin sends — an
    outbound message announces the hop it creates. It is also where the hop
    budget is enforced: a Run already at the limit gets no A2A plugin at all,
    so the chain cannot grow by another hop even if a peer ignores the
    announced depth. Refusing here rather than at call time is deliberate. The
    model never sees a Tool it would be told off for using, and a Run that
    cannot delegate answers with what it has instead of spending a turn
    discovering it may not.
    """

    def __init__(
        self, max_entries: int = 256, *, transport: A2ATransport | None = None
    ) -> None:
        self._plugins: OrderedDict[tuple[str, int, str], A2AToolPlugin] = OrderedDict()
        self._max_entries = max(1, max_entries)
        # A host may supply its own transport, exactly as the MCP bridge takes
        # a session factory. Without it there is no way to exercise delegation
        # against anything but a real network peer.
        self._transport = transport

    def get(
        self,
        user_id: str,
        records: Iterable[A2AAgentRecord],
        *,
        call_depth: int = 0,
    ) -> A2AToolPlugin | None:
        if call_depth >= MAX_CALL_DEPTH:
            return None
        agents = a2a_agent_configs(records)
        if not agents:
            return None
        key = (user_id, call_depth, A2AToolPlugin.servers_fingerprint(agents))
        cached = self._plugins.get(key)
        if cached is not None:
            self._plugins.move_to_end(key)
            return cached
        plugin = A2AToolPlugin(agents, call_depth=call_depth, transport=self._transport)
        self._plugins[key] = plugin
        while len(self._plugins) > self._max_entries:
            self._plugins.popitem(last=False)
        return plugin

    def invalidate(self, user_id: str) -> None:
        """Forget this user's plugins so the next Run re-reads their cards.

        A card is read once per entry and the fingerprint covers only the
        transport, so a peer that was down when it was first read, or that has
        since published a new skill, would otherwise stay stale forever with no
        way for the tenant to recover.
        """

        for key in [item for item in self._plugins if item[0] == user_id]:
            self._plugins.pop(key, None)

    def clear(self) -> None:
        self._plugins.clear()
