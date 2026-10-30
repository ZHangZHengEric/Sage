"""Archive-only compatibility for budgets removed from the runtime schema.

Old immutable packages and Run hashes included these values. Preserve their
provenance when reading/serializing a whole manifest, never as runtime limits.
"""

from pydantic import TypeAdapter

from sagents.v2.contracts.common import NonNegativeInt, PositiveInt
from sagents.v2.package.manifest.runtime import RETIRED_BUDGET_FIELDS


def legacy_budget_values(value):
    if not isinstance(value, dict):
        return {}
    scopes = {None: value.get("policies", {})}
    scopes.update(value.get("agents", {}))
    result = {}
    for scope, definition in scopes.items():
        budgets = definition.get("budgets", {}) if isinstance(definition, dict) else {}
        if not isinstance(budgets, dict):
            continue
        retained = {}
        for key in RETIRED_BUDGET_FIELDS:
            if budgets.get(key) is not None:
                adapter = TypeAdapter(PositiveInt if key == "system_tokens" else NonNegativeInt)
                retained[key] = adapter.validate_python(budgets[key])
        if retained:
            result[scope] = retained
    return result


def restore_legacy_budget_values(payload, values):
    for scope, budgets in values.items():
        definition = payload.get("policies") if scope is None else payload.get("agents", {}).get(scope)
        if isinstance(definition, dict) and isinstance(definition.get("budgets"), dict):
            definition["budgets"].update(budgets)
    return payload


def historical_budget_payload(payload):
    """Restore historical null defaults without replacing configured values."""
    for budgets in (
        payload["policies"]["budgets"],
        *(definition["budgets"] for definition in payload["agents"].values()),
    ):
        for key in RETIRED_BUDGET_FIELDS:
            budgets.setdefault(key, None)
    return payload


def historical_policy_values(manifest, agent_id):
    """Hash provenance only; these are never passed to runtime constructors."""
    result = {}
    for key, target in (("system_tokens", "max_system_tokens"),
                        ("protected_recent_tokens", "protected_recent_tokens")):
        values = [scope[key] for scope in (
            manifest._legacy_budget_values.get(None, {}),
            manifest._legacy_budget_values.get(agent_id, {}),
        ) if key in scope]
        result[target] = min(values) if values else None
    return result
