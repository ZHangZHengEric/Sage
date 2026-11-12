"""SDK checks and public conformance probes exercise the same contracts."""

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    CapabilityRequirement,
    ExtensionDescriptor,
    ExtensionHost,
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
    capability_contract_inventory,
)
from sagents.v2.runtime.extensions.capability_contracts import module_contract_inventory
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.skill import InMemorySkillProvider
from sagents.v2.testing import check_provider_contract, run_skill_provider_conformance
from tests.sagents.v2.test_skill_provider_matrix import bundle


def registration(provider, *, features=(), stop=None):
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.skill-provider",
            name="Test Skill provider",
            version="1",
            supported_scopes=frozenset({ExtensionScope.RUN}),
            provides=(
                CapabilityOffer(
                    capability="skill.provider", api_version="2.1", features=features
                ),
            ),
        ),
        factory=lambda *_: provider,
        stop=stop,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("synchronous", [False, True])
async def test_invalid_provider_is_rejected_and_rolled_back(synchronous):
    provider = object()
    stops = []
    host = ExtensionHost()
    host.register(
        registration(
            provider, stop=lambda value, reason: stops.append((value, reason.value))
        )
    )
    plan = host.plan(
        (CapabilityRequirement(capability="skill.provider", api_version="2"),)
    )
    context = ExtensionScopeContext(
        scope=ExtensionScope.RUN, scope_id="run", run_id="run"
    )
    with pytest.raises(SageV2Error, match="list_skills, get_skill, fetch") as caught:
        if synchronous:
            host.open_scope_sync(context, plan)
        else:
            await host.open_scope(context, plan)
    assert caught.value.info.code == "extension.provider_contract_mismatch"
    assert stops == [(provider, "start_failed")]


def test_unknown_feature_is_rejected_at_registration():
    with pytest.raises(SageV2Error) as caught:
        ExtensionHost().register(registration(object(), features=("skill.lookup",)))
    assert caught.value.info.code == "extension.unknown_feature"


@pytest.mark.asyncio
async def test_skill_conformance_searches_an_authorized_subset():
    provider = InMemorySkillProvider(
        (bundle("alpha", "needle"), bundle("omega", "needle"))
    )
    await run_skill_provider_conformance(
        provider,
        run_id="run",
        names=("alpha", "omega"),
        search_query="needle",
        expected_match="omega",
    )
    with pytest.raises(AssertionError, match="search_skills"):
        check_provider_contract(
            "skill.provider", _LegacyProvider(provider), features=("skill.search",)
        )
    check_provider_contract("skill.provider", _LegacyProvider(provider))


class _LegacyProvider:
    def __init__(self, source):
        self.list_skills = source.list_skills
        self.get_skill = source.get_skill
        self.fetch = source.fetch


def test_builtin_registry_projects_canonical_capabilities_and_implementations():
    registry = builtin_extension_registry()
    inventory = module_contract_inventory(registry)
    contracts = capability_contract_inventory()
    assert {
        offer.capability
        for registration in registry.registrations()
        for offer in registration.descriptor.provides
    } <= contracts.keys()
    assert (
        inventory["skill.provider"]["module"] == inventory["skill.management"]["module"]
    )
    filesystem = next(
        option
        for option in inventory["skill.provider"]["implementations"]
        if "filesystem" in option["id"]
    )
    assert {"id": "skill.search", "status": "declared"} in filesystem["features"]
    readonly = next(
        option
        for option in inventory["skill.management"]["implementations"]
        if option["id"] == filesystem["id"]
    )
    assert {"id": "skill.publish", "status": "unsupported"} in readonly["features"]
    assert inventory["skill.loader"]["implementations"][0]["sdk_managed"]


@pytest.mark.asyncio
async def test_model_and_tool_conformance_accept_standard_providers():
    from sagents.v2.model.contracts import ModelRequest
    from sagents.v2.testing import (
        run_model_provider_conformance,
        run_tool_provider_conformance,
    )
    from sagents.v2.tool.contracts import ToolCall
    from sagents.v2.tool.decorated import DecoratedToolProvider
    from sagents.v2.tool.decorators import tool
    from tests.sagents.v2.test_agent_management_matrix import context, model

    class Echo:
        @tool(description="Return a fixture value")
        async def echo(self, value: str) -> str:
            return value

    await run_model_provider_conformance(
        model(),
        ModelRequest(
            request_id="request", run_id="run", model_binding="test", messages=()
        ),
    )
    await run_tool_provider_conformance(
        DecoratedToolProvider(Echo()),
        ToolCall(
            tool_call_id="call",
            tool_name="echo",
            operation_id="operation",
            idempotency_key="key",
            owner_run_id="run",
            arguments={"value": "fixture"},
        ),
        context(),
    )


@pytest.mark.asyncio
async def test_skill_management_conformance_accepts_memory_repository():
    from sagents.v2.skill.plugins.repository import MemorySkillRepository
    from sagents.v2.testing import run_skill_management_conformance

    repository = MemorySkillRepository()
    try:
        await run_skill_management_conformance(
            repository,
            initial=bundle("demo", "first"),
            update=bundle("demo", "second"),
            stale=bundle("demo", "stale"),
            run_id="run",
        )
    finally:
        await repository.close()


def test_self_configuration_can_be_absent_when_the_run_has_no_grant():
    check_provider_contract("agent.self-configuration", None)
    with pytest.raises(AssertionError, match="bind"):
        check_provider_contract("agent.self-configuration", object())
    with pytest.raises(AssertionError, match="list_skills"):
        check_provider_contract("skill.provider", None)


@pytest.mark.asyncio
async def test_skill_search_declaration_rejects_incompatible_call_shape():
    class WrongSearchSignature(InMemorySkillProvider):
        async def search_skills(self):
            return ()

    host = ExtensionHost()
    host.register(registration(WrongSearchSignature(()), features=("skill.search",)))
    plan = host.plan(
        (CapabilityRequirement(capability="skill.provider", api_version="2"),)
    )
    context = ExtensionScopeContext(
        scope=ExtensionScope.RUN, scope_id="run", run_id="run"
    )
    with pytest.raises(SageV2Error, match="search_skills.*incompatible signature"):
        await host.open_scope(context, plan)
