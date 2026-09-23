"""A2A plugins are shared by peer set and hop depth, not rebuilt per Run.

The depth half of the key is also the outbound hop budget: a Run that is
already the fourth agent in a chain gets no A2A plugin at all, so it cannot
add a fifth.
"""

from __future__ import annotations

from sagents.v2.tool.plugins.a2a import MAX_CALL_DEPTH

from app.server_v2.domain.catalog import A2AAgentRecord
from app.server_v2.infrastructure.a2a_client import A2APluginCache


def _peer(name: str, *, url: str = "", disabled: bool = False) -> A2AAgentRecord:
    return A2AAgentRecord(
        name=name,
        url=url or f"https://{name}.example.com",
        disabled=disabled,
    )


def test_same_peer_set_reuses_one_plugin_across_runs():
    cache = A2APluginCache()
    records = [_peer("researcher")]

    first = cache.get("user_1", records)
    second = cache.get("user_1", list(records))

    assert first is not None
    assert second is first


def test_tenants_do_not_share_a_plugin():
    """A plugin holds the credential it discovered with."""

    cache = A2APluginCache()
    records = [_peer("researcher")]

    assert cache.get("user_1", records) is not cache.get("user_2", records)


def test_rotating_a_key_builds_a_new_plugin():
    cache = A2APluginCache()
    before = cache.get("user_1", [_peer("researcher")])

    rotated = _peer("researcher").model_copy(update={"api_key": "sk-new"})

    assert cache.get("user_1", [rotated]) is not before


def test_disabled_and_empty_peer_sets_produce_no_plugin():
    cache = A2APluginCache()

    assert cache.get("user_1", []) is None
    assert cache.get("user_1", [_peer("researcher", disabled=True)]) is None


def test_a_run_at_the_hop_limit_gets_no_peers_at_all():
    """Refusing here is what makes the budget hold without trusting the peer.

    The alternative is to hand the Run the Tools and reject the call, which
    spends a model turn discovering a capability it was never going to have.
    """

    cache = A2APluginCache()
    records = [_peer("researcher")]

    assert cache.get("user_1", records, call_depth=MAX_CALL_DEPTH - 1) is not None
    assert cache.get("user_1", records, call_depth=MAX_CALL_DEPTH) is None
    assert cache.get("user_1", records, call_depth=MAX_CALL_DEPTH + 7) is None


def test_depth_is_part_of_the_identity_because_it_is_part_of_what_is_sent():
    """Each plugin announces its own depth, so one cannot stand in for another."""

    cache = A2APluginCache()
    records = [_peer("researcher")]

    first = cache.get("user_1", records, call_depth=0)
    second = cache.get("user_1", records, call_depth=1)

    assert first is not None and second is not None
    assert first is not second
    assert (first.call_depth, second.call_depth) == (0, 1)


def test_cache_is_bounded_by_eviction():
    cache = A2APluginCache(max_entries=2)
    first = cache.get("user_1", [_peer("a")])
    cache.get("user_1", [_peer("b")])
    cache.get("user_1", [_peer("c")])

    assert cache.get("user_1", [_peer("a")]) is not first


def test_invalidate_forces_a_fresh_card_for_that_tenant_only():
    cache = A2APluginCache()
    mine = cache.get("user_1", [_peer("researcher")])
    deeper = cache.get("user_1", [_peer("researcher")], call_depth=1)
    theirs = cache.get("user_2", [_peer("researcher")])

    cache.invalidate("user_1")

    assert cache.get("user_1", [_peer("researcher")]) is not mine
    assert cache.get("user_1", [_peer("researcher")], call_depth=1) is not deeper
    assert cache.get("user_2", [_peer("researcher")]) is theirs


def test_an_unusable_peer_costs_its_own_tools_and_not_the_run():
    """A row that cannot be projected is the same as a peer that is down."""

    cache = A2APluginCache()
    broken = _peer("researcher").model_construct(name="researcher", url="not-a-url")

    plugin = cache.get("user_1", [broken, _peer("good")])

    assert plugin is not None
    assert [item.name for item in plugin.agents] == ["good"]
