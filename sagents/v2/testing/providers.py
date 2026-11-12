"""Provider probes that can be run by third-party authors in isolated fixtures."""

from __future__ import annotations

from sagents.v2.runtime.extensions.capability_contracts import (
    capability_contract_inventory,
    missing_provider_members,
)


def check_provider_contract(
    capability: str,
    provider,
    *,
    features: tuple[str, ...] = (),
) -> None:
    """Check required members and declared features for an SDK capability."""
    contract = capability_contract_inventory().get(capability)
    if contract is None:
        raise ValueError(f"Unknown SDK capability: {capability}")
    known_features = {item["id"] for item in contract["features"]}
    if unknown := set(features) - known_features:
        raise ValueError(f"Unknown {capability} features: {', '.join(sorted(unknown))}")
    missing = missing_provider_members(capability, provider, features=features)
    if missing:
        raise AssertionError(f"{capability} is missing {', '.join(missing)}")


async def run_skill_provider_conformance(
    provider,
    *,
    run_id: str,
    names: tuple[str, ...],
    search_query: str | None = None,
    expected_match: str | None = None,
) -> None:
    """Probe an isolated catalog seeded with the given Skills.

    For search, seed at least two matching Skills and give one allowed name as
    expected_match. The other matching Skills exercise the authorization boundary.
    """
    features = ("skill.search",) if search_query is not None else ()
    check_provider_contract("skill.provider", provider, features=features)
    catalog = await provider.list_skills(run_id=run_id)
    by_name = {item.name: item for item in catalog}
    assert len(by_name) == len(catalog), "Skill catalog contains duplicate names"
    for name in names:
        descriptor = await provider.get_skill(name, run_id=run_id)
        bundle = await provider.fetch(name, run_id=run_id)
        assert descriptor == by_name.get(name), (
            f"Skill lookup disagrees with catalog: {name}"
        )
        assert bundle.descriptor == descriptor, (
            f"Skill fetch disagrees with lookup: {name}"
        )
        assert "SKILL.md" in bundle.files, f"Missing SKILL.md: {name}"
    if search_query is None:
        return
    if expected_match is None or expected_match not in names:
        raise ValueError("expected_match must be one of the seeded Skills")
    for allowed, expected in (
        (frozenset({expected_match}), (expected_match,)),
        (frozenset(), ()),
    ):
        matches = await provider.search_skills(
            search_query, run_id=run_id, allowed_names=allowed, limit=1
        )
        assert tuple(item.name for item in matches) == expected, (
            "Skill search violated its grant or ranking"
        )


async def run_skill_management_conformance(
    provider, *, initial, update, stale, run_id: str
) -> None:
    """Probe publishing, pinning, and conflict rollback in an isolated repository.

    Supply three distinct bundles for one unused Skill name and a fresh Run ID.
    """
    from sagents.v2.contracts.errors import SageV2Error

    check_provider_contract(
        "skill.management",
        provider,
        features=("skill.publish", "skill.version-history"),
    )
    name = initial.descriptor.name
    if {name, update.descriptor.name, stale.descriptor.name} != {name}:
        raise ValueError("initial, update and stale bundles must share a name")
    first = await provider.publish(initial)
    assert await provider.get_skill(name, run_id=run_id) == first
    second = await provider.publish(update, expected_version=first.version)
    assert second.version != first.version, (
        "Distinct Skill content reused the same version"
    )
    assert (await provider.fetch(name, run_id=run_id)).descriptor == first, (
        "An admitted Run changed versions"
    )
    try:
        await provider.publish(stale, expected_version=first.version)
    except SageV2Error as error:
        assert error.info.code == "skill.publish_conflict", (
            "Publishing returned the wrong conflict error"
        )
    else:
        raise AssertionError("A stale publisher overwrote a newer version")
    assert {item.version for item in await provider.list_versions(name)} == {
        first.version,
        second.version,
    }
    assert (await provider.fetch(name, run_id=f"{run_id}-next")).descriptor == second


async def run_tool_provider_conformance(provider, call, context) -> None:
    """Exercise catalog and execution with a caller-supplied isolated ToolCall."""
    check_provider_contract("tool.provider", provider)
    definitions = await provider.catalog.list_tools(run_id=call.owner_run_id)
    names = {item.name for item in definitions}
    assert len(names) == len(definitions), "Tool catalog contains duplicate names"
    definition = await provider.catalog.get_tool(
        call.tool_name, run_id=call.owner_run_id
    )
    assert definition in definitions, "Tool lookup disagrees with catalog"
    result = await provider.executor.execute(call, context)
    assert result.tool_call_id == call.tool_call_id, (
        "Tool execution returned a different call ID"
    )
    assert result.operation_id == call.operation_id, (
        "Tool execution returned a different operation ID"
    )
    assert result.error is None, f"Fixture tool failed: {result.error}"


async def run_model_provider_conformance(provider, request) -> None:
    """Validate a successful isolated ModelRequest and its normalized stream."""
    from sagents.v2.model.contracts import ModelEventKind, ModelStreamEvent

    check_provider_contract("model.provider", provider)
    capabilities = await provider.capabilities(request.model_binding)
    assert capabilities is not None, "Model capabilities are missing"
    completed = False
    async for event in provider.stream(request):
        assert isinstance(event, ModelStreamEvent), "Model emitted a non-standard event"
        assert not completed, "Model emitted events after completion"
        if event.kind == ModelEventKind.COMPLETED:
            assert event.response is not None, (
                "Completed model event is missing its response"
            )
            completed = True
    assert completed, "Model stream did not complete"
