"""MCP plugins are shared by Run, not rebuilt per Run."""

from __future__ import annotations

from app.v2.server.catalog.records import McpServerRecord
from app.v2.server.runtime.integrations.mcp import McpPluginCache


def _server(name: str, *, url: str = "", disabled: bool = False):
    return McpServerRecord(
        name=name,
        protocol="streamable_http",
        url=url or f"https://mcp.example.com/{name}",
        disabled=disabled,
    )


def test_same_server_set_reuses_one_plugin_across_runs():
    cache = McpPluginCache()
    records = [_server("files")]

    first = cache.get("user_1", records)
    second = cache.get("user_1", list(records))

    assert first is not None
    assert second is first


def test_users_do_not_share_a_plugin():
    cache = McpPluginCache()
    records = [_server("files")]

    assert cache.get("user_1", records) is not cache.get("user_2", records)


def test_reconfiguration_leaves_the_previous_plugin_intact():
    cache = McpPluginCache()
    before = cache.get("user_1", [_server("files")])

    after = cache.get("user_1", [_server("files"), _server("search")])

    assert after is not before
    # The Run still executing against the old set keeps its own discovery.
    assert before is not None and [item.name for item in before.servers] == ["files"]
    assert cache.get("user_1", [_server("files")]) is before


def test_disabled_and_empty_server_sets_produce_no_plugin():
    cache = McpPluginCache()

    assert cache.get("user_1", []) is None
    assert cache.get("user_1", [_server("files", disabled=True)]) is None


def test_cache_is_bounded_by_eviction():
    cache = McpPluginCache(max_entries=2)
    first = cache.get("user_1", [_server("a")])
    cache.get("user_1", [_server("b")])
    cache.get("user_1", [_server("c")])

    assert cache.get("user_1", [_server("a")]) is not first


def test_lru_refresh_protects_recently_used_entry():
    """Accessing an entry moves it to the end so the least-recently-used is evicted.

    With capacity 2, insert A and B, then re-access A before inserting C.
    A must still be the original object; B must have been evicted.
    This distinguishes true LRU from pure insertion-order (FIFO) eviction.
    """
    cache = McpPluginCache(max_entries=2)
    a = cache.get("user_1", [_server("a")])
    b = cache.get("user_1", [_server("b")])
    # Refresh A so it becomes most-recently-used.
    assert cache.get("user_1", [_server("a")]) is a
    # Inserting C should evict B (the least recently used), not A.
    cache.get("user_1", [_server("c")])

    assert cache.get("user_1", [_server("a")]) is a
    assert cache.get("user_1", [_server("b")]) is not b


def test_order_independent_server_set_reuses_plugin():
    """The same set of servers requested in opposite orders must hit the same cache entry.

    servers_fingerprint sorts by name, so order must not affect identity.
    """
    cache = McpPluginCache()
    forward = cache.get("user_1", [_server("alpha"), _server("beta")])
    reverse = cache.get("user_1", [_server("beta"), _server("alpha")])

    assert forward is not None
    assert reverse is forward


def test_invalidate_forces_rediscovery_for_that_user_only():
    cache = McpPluginCache()
    mine = cache.get("user_1", [_server("files")])
    theirs = cache.get("user_2", [_server("files")])

    cache.invalidate("user_1")

    assert cache.get("user_1", [_server("files")]) is not mine
    assert cache.get("user_2", [_server("files")]) is theirs
