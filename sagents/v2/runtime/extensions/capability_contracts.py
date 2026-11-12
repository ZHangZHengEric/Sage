"""SDK-owned provider contracts shared by composition, testing and inventory."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import import_module
from inspect import signature
from typing import Any

from sagents.v2.runtime.extensions.versions import version_satisfies


@dataclass(frozen=True)
class CapabilityFeature:
    id: str
    members: tuple[str, ...] = ()
    required_when: str = ""
    guarantee: str = ""


@dataclass(frozen=True)
class CapabilityContract:
    version: str = "2"
    methods: tuple[str, ...] = ()
    attributes: tuple[str, ...] = ()
    protocol: str = ""
    features: tuple[CapabilityFeature, ...] = ()
    conformance: str = ""
    sdk_managed: bool = False
    nullable_provider: bool = False


def _methods(names: str) -> tuple[str, ...]:
    return tuple(names.split())


def _feature(id: str, members: str = "", *, when: str = "", guarantee: str = ""):
    return CapabilityFeature(id, _methods(members), when, guarantee)


def _contract(
    methods: str = "",
    *,
    attributes: str = "",
    protocol: str = "",
    features: tuple[CapabilityFeature, ...] = (),
    conformance: str = "",
    version: str = "2",
    sdk_managed: bool = False,
    nullable_provider: bool = False,
):
    return CapabilityContract(
        version,
        _methods(methods),
        _methods(attributes),
        protocol,
        features,
        conformance,
        sdk_managed,
        nullable_provider,
    )


_CONTRACTS = {
    "agent.approval-memory": _contract("lookup remember forget list_remembered"),
    "agent.continuation-policy": _contract("decide"),
    "agent.management": _contract(
        "schema resources events list get validate save fork activate run status control"
    ),
    "agent.output-checker": _contract("check"),
    "agent.self-configuration": _contract(
        "bind segments prepare verify_checkpoint", nullable_provider=True
    ),
    "agent.tool-policy": _contract("decide"),
    "artifact.store": _contract("put get delete"),
    "context.reducer": _contract("reduce"),
    "context.segment-provider": _contract("segments"),
    "context.summarizer": _contract("summarize"),
    "context.summary-store": _contract("get save delete"),
    "credentials.provider": _contract("resolve"),
    "derived-state.store": _contract(
        "get_derived_state put_derived_state delete_derived_state forget_session"
    ),
    "execution.binding": _contract("accept_configuration acquire close"),
    "execution.dispatcher": _contract(
        "start submit submit_cleanup close", sdk_managed=True
    ),
    "execution.environment": _contract(
        attributes="run_id context sandbox grant_issuer", sdk_managed=True
    ),
    "execution.job-runtime": _contract(
        protocol="runtime.execution.jobs.provider:JobRuntime",
        features=(
            _feature(
                "execution.job-recovery", guarantee="durable_across_process_restart"
            ),
            _feature("execution.job-reconnect", guarantee="supports_reconnect"),
            _feature("execution.job-adoption", guarantee="supports_adoption"),
            _feature("execution.job-remote-cancel", guarantee="supports_remote_cancel"),
        ),
    ),
    "execution.model-budget": _contract("wrap"),
    "execution.sandbox": _contract(
        protocol="runtime.execution.sandbox.provider:SandboxProvider",
        version="3",
        features=(
            _feature("sandbox.snapshot", guarantee="supports_snapshot"),
            _feature("sandbox.reconnect", guarantee="supports_reconnect"),
            _feature("sandbox.secret-injection", guarantee="supports_secret_injection"),
            _feature("sandbox.terminal-purge", guarantee="supports_terminal_purge"),
        ),
    ),
    "execution.scheduler": _contract(
        protocol="runtime.execution.scheduler.provider:Scheduler",
        features=(
            _feature(
                "scheduler.distributed-claims", guarantee="supports_distributed_claims"
            ),
            _feature(
                "scheduler.atomic-tenant-quota",
                guarantee="supports_atomic_tenant_quota",
            ),
        ),
        conformance="run_scheduler_conformance",
    ),
    "execution.tool-runtime": _contract(
        attributes="sandbox grant_issuer", sdk_managed=True
    ),
    "flow.node": _contract("run"),
    "interface.protocol-adapter": _contract("capabilities translate"),
    "memory.provider": _contract(
        "capabilities recall remember forget get health",
        features=(
            _feature("memory.filtering", guarantee="supports_filtering"),
            _feature("memory.delete", guarantee="supports_delete"),
        ),
    ),
    "memory.recall-query": _contract("generate"),
    "model.provider": _contract(
        "capabilities stream",
        features=(
            _feature(
                "model.capability-probe", "probe_capabilities", when="capability_probe"
            ),
        ),
        conformance="run_model_provider_conformance",
    ),
    "observability.provider": _contract(
        "close export_evidence",
        attributes="logs traces diagnostics",
        features=(
            _feature("observability.trace-export", guarantee="exports_otlp"),
            _feature(
                "observability.evidence-query", guarantee="supports_evidence_query"
            ),
        ),
    ),
    "package.registry": _contract(
        "save_draft validate test publish retire get list", attributes="capabilities"
    ),
    "package.resolver": _contract(
        "resolve resolve_run_config resolve_child_run_config", sdk_managed=True
    ),
    "session-memory.provider": _contract(
        "capabilities sync recall forget_session health"
    ),
    "session.access": _contract(
        "get_run get_run_result get_session get_start_command read_events subscribe_events delete_session",
        sdk_managed=True,
    ),
    "session.store": _contract(
        protocol="runtime.session.contracts:SessionStore",
        features=(
            _feature(
                "session.durable-recovery", guarantee="durable_across_process_restart"
            ),
            _feature("session.multi-process-writes", guarantee="multi_process_writes"),
            _feature("session.atomic-worker-fence", guarantee="atomic_worker_fence"),
        ),
        conformance="run_session_store_recovery_conformance",
    ),
    "skill.loader": _contract("load loaded", sdk_managed=True),
    "skill.loading": _contract("create_loader"),
    "skill.management": _contract(
        "list_skills get_skill fetch publish list_versions",
        features=(
            _feature("skill.publish", guarantee="writable"),
            _feature("skill.version-history", guarantee="versioned"),
        ),
        conformance="run_skill_management_conformance",
    ),
    "skill.provider": _contract(
        "list_skills get_skill fetch",
        features=(
            _feature("skill.search", "search_skills", when="search_skills"),
            _feature("skill.latest", "fetch_latest"),
            _feature("skill.restore-version", "fetch_for_restore"),
        ),
        conformance="run_skill_provider_conformance",
    ),
    "skill.workspace": _contract(
        "materialize",
        features=(
            _feature("skill.edit", "begin_edit resolve_bundle", when="edit_skill"),
            _feature("skill.reattach", "reattach"),
        ),
    ),
    "tool.provider": _contract(
        "catalog.list_tools catalog.get_tool executor.execute executor.reconcile",
        features=(
            _feature("tool.cancel", "executor.cancel"),
            _feature("tool.release-run", "executor.release_run"),
        ),
        conformance="run_tool_provider_conformance",
    ),
    "tool.result-processor": _contract("process"),
    "tool.selection-policy": _contract(
        "prepare select expand_tools expanded_tools restore_expanded_tools release_run"
    ),
    "workspace.initializer": _contract("initialize"),
}


@cache
def _members(contract: CapabilityContract) -> tuple[tuple[str, ...], tuple[str, ...]]:
    methods, attributes = list(contract.methods), list(contract.attributes)
    if contract.protocol:
        module, name = contract.protocol.split(":")
        protocol = getattr(import_module(f"sagents.v2.{module}"), name)
        for member, value in vars(protocol).items():
            if member.startswith("_"):
                continue
            if isinstance(value, property):
                attributes.append(member)
            elif callable(value):
                methods.append(member)
        attributes.extend(
            name
            for name in getattr(protocol, "__annotations__", {})
            if not name.startswith("_")
        )
    return tuple(methods), tuple(attributes)


def _member(provider: Any, path: str):
    for part in path.split("."):
        provider = getattr(provider, part, None)
    return provider


# Check call shapes used by the SDK, while permitting decorators, **kwargs,
# and callable objects that return an awaitable.
_SKILL_CALL_SHAPES = {
    "list_skills": ((), {"run_id": "run"}),
    "get_skill": (("skill",), {"run_id": "run"}),
    "fetch": (("skill",), {"run_id": "run"}),
    "fetch_latest": (("skill",), {"run_id": "run"}),
    "fetch_for_restore": (("skill",), {"run_id": "run", "version": "accepted"}),
    "search_skills": (
        ("query",),
        {"run_id": "run", "allowed_names": frozenset(), "limit": 1},
    ),
    "publish": ((None,), {"expected_version": None}),
    "list_versions": (("skill",), {}),
}


def _accepts_skill_call(member, method: str) -> bool:
    args, kwargs = _SKILL_CALL_SHAPES[method]
    try:
        call_signature = signature(member)
    except (TypeError, ValueError):
        return True  # Native callables may expose no introspectable signature.
    try:
        call_signature.bind(*args, **kwargs)
    except TypeError:
        return False
    return True


def missing_provider_members(
    capability: str,
    provider: Any,
    *,
    api_version: str | None = None,
    features: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Check structural requirements without executing provider operations."""
    contract = _CONTRACTS.get(capability)
    if contract is None or (
        api_version is not None and not version_satisfies(api_version, contract.version)
    ):
        return ()
    if provider is None and contract.nullable_provider:
        return ()
    methods, attributes = _members(contract)
    required = methods + tuple(
        member
        for feature in contract.features
        if feature.id in features
        for member in feature.members
    )
    missing = []
    for member in required:
        value = _member(provider, member)
        if not callable(value):
            missing.append(member)
        elif capability in {
            "skill.provider",
            "skill.management",
        } and not _accepts_skill_call(value, member):
            missing.append(f"{member} (incompatible signature)")
    missing.extend(member for member in attributes if not hasattr(provider, member))
    return tuple(missing)


def capability_contract_inventory() -> dict[str, dict]:
    """Return fresh, JSON-safe contract definitions for host tooling."""
    return {
        name: {
            "api_version": contract.version,
            "required_members": [*_members(contract)[0], *_members(contract)[1]],
            "features": [
                {
                    "id": feature.id,
                    "members": list(feature.members),
                    "required_when": feature.required_when,
                }
                for feature in contract.features
            ],
            "conformance": contract.conformance or None,
            "sdk_managed": contract.sdk_managed,
            "nullable_provider": contract.nullable_provider,
        }
        for name, contract in _CONTRACTS.items()
    }


def unknown_provider_features(offer) -> tuple[str, ...]:
    contract = _CONTRACTS.get(offer.capability)
    if (
        contract is None
        or not offer.features
        or not version_satisfies(offer.api_version, contract.version)
    ):
        return ()
    expected = {feature.id for feature in contract.features}
    return tuple(sorted(set(offer.features) - expected))


def declared_provider_features(descriptor) -> dict[str, list[dict]]:
    """Report declarations without asserting that runtime behavior was verified."""
    result = {}
    for offer in descriptor.provides:
        contract = _CONTRACTS.get(offer.capability)
        if contract is None or not version_satisfies(
            offer.api_version, contract.version
        ):
            continue
        result[offer.capability] = [
            {
                "id": feature.id,
                "status": (
                    "declared"
                    if feature.id in offer.features
                    or descriptor.capabilities.get(feature.guarantee) is True
                    else "unsupported"
                    if descriptor.capabilities.get(feature.guarantee) is False
                    else "not_declared"
                ),
            }
            for feature in contract.features
        ]
    return result


def module_contract_inventory(registry, *, host_registrations=()) -> dict[str, dict]:
    """Project each SDK contract and its registered implementations for clients."""
    contracts = capability_contract_inventory()
    groups = {
        "derived-state.store": "session",
        "execution.model-budget": "model",
        "execution.tool-runtime": "tool",
    }
    for capability, contract in contracts.items():
        contract["module"] = groups.get(capability, capability.split(".")[0])
        contract["implementations"] = []
    registrations = {
        value.descriptor.plugin_id: value
        for value in (*registry.registrations(), *host_registrations)
    }
    for registration in registrations.values():
        descriptor = registration.descriptor
        features = declared_provider_features(descriptor)
        for offer in descriptor.provides:
            if offer.capability not in contracts:
                continue
            contracts[offer.capability]["implementations"].append(
                {
                    "id": descriptor.plugin_id,
                    "api_version": offer.api_version,
                    "provider_name": offer.name,
                    "name": descriptor.name,
                    "available": descriptor.availability.available,
                    "sdk_managed": descriptor.sdk_managed
                    or contracts[offer.capability]["sdk_managed"],
                    "features": features.get(offer.capability, []),
                }
            )
    return contracts


def module_contracts_for(
    capability: str, inventory: dict[str, dict]
) -> dict[str, dict]:
    contract = inventory.get(capability)
    if contract is None:
        return {}
    return {
        name: item
        for name, item in inventory.items()
        if item["module"] == contract["module"]
    }
