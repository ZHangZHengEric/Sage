"""Public runtime configuration exposes providers, not their internal ports."""

import json

import pytest

from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions.official import builtin_extension_registry


@pytest.mark.parametrize(
    "capability",
    [
        "tool.catalog",
        "tool.executor",
        "skill.catalog",
        "skill.source",
        "context.unit-compactor",
    ],
)
def test_removed_capability_configuration_is_rejected(capability):
    with pytest.raises(ValueError, match="removed"):
        RuntimeConfig(capabilities={capability: {"plugin": "custom.plugin"}})


def test_inventory_exposes_one_provider_per_tool_and_skill_source():
    registry = builtin_extension_registry()
    for plugin, capability in (
        ("sage.tool.official", "tool.provider"),
        ("sage.tool.mcp", "tool.provider"),
        ("sage.tool.ephemeral", "tool.provider"),
        ("sage.skill.filesystem", "skill.provider"),
        ("sage.skill.repository.sqlite", "skill.provider"),
    ):
        offers = registry.get(plugin).descriptor.provides
        assert sum(offer.capability == capability for offer in offers) == 1
        assert not any(
            offer.capability
            in {
                "tool.catalog",
                "tool.executor",
                "skill.catalog",
                "skill.source",
            }
            for offer in offers
        )
    assert not registry.contains("sage.context.unit-compactor.reference")


@pytest.mark.parametrize("field", ["capabilities", "required_guarantees"])
def test_removed_names_are_rejected_in_serialized_runtime(field):
    value = (
        {"plugin": "custom.plugin"} if field == "capabilities" else {"durable": True}
    )
    with pytest.raises(ValueError, match="removed"):
        RuntimeConfig.model_validate_json(json.dumps({field: {"tool.executor": value}}))
