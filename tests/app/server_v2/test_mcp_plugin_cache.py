"""MCP plugins are shared by Run, not rebuilt per Run."""

from __future__ import annotations

from app.server_v2.domain.catalog import McpServerRecord
from app.server_v2.infrastructure.mcp import McpPluginCache


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


def test_invalidate_forces_rediscovery_for_that_user_only():
    cache = McpPluginCache()
    mine = cache.get("user_1", [_server("files")])
    theirs = cache.get("user_2", [_server("files")])

    cache.invalidate("user_1")

    assert cache.get("user_1", [_server("files")]) is not mine
    assert cache.get("user_2", [_server("files")]) is theirs
