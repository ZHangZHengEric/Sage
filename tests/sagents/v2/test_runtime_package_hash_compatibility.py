"""New runtime defaults preserve durable package references."""

import hashlib
import json

import pytest

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from tests.sagents.v2.test_agent_management_matrix import bundle


def test_runtime_defaults_preserve_legacy_package_hash_with_dependencies():
    package = bundle().model_copy(update={"dependencies": {"child": bundle("2.0.0")}})
    payload = package.model_dump(mode="json")

    def legacy(value):
        runtime = value["manifest"]["runtime"]
        for name in ("start_workers", "check_readiness", "state_root"):
            runtime.pop(name, None)
        for selection in runtime["capabilities"].values():
            for item in selection if isinstance(selection, list) else [selection]:
                item.pop("grant_tools", None)
        for agent in value["manifest"]["agents"].values():
            if not agent.get("preload_skills"):
                agent.pop("preload_skills", None)
        for child in value.get("dependencies", {}).values():
            legacy(child)

    legacy(payload)
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert AgentPackageBundle.model_validate(payload).content_hash == expected
    assert package.content_hash == expected


@pytest.mark.parametrize("field,value", [
    ("start_workers", False), ("check_readiness", True), ("state_root", "/state"),
])
def test_nondefault_runtime_controls_are_serialized_and_change_package_hash(field, value):
    package = bundle()
    changed = package.model_dump(mode="json")
    changed["manifest"]["runtime"][field] = value
    updated = AgentPackageBundle.model_validate(changed)
    assert updated.manifest.runtime.model_dump()[field] == value
    assert updated.content_hash != package.content_hash
    assert RuntimeConfig.model_validate(updated.manifest.runtime.model_dump()).model_dump()[field] == value


def test_tool_grants_are_serialized_only_when_enabled():
    selection = CapabilitySelection(plugin="test.tools")
    assert "grant_tools" not in selection.model_dump()
    granted = selection.model_copy(update={"grant_tools": True})
    assert granted.model_dump()["grant_tools"] is True
    assert CapabilitySelection.model_validate(granted.model_dump()).grant_tools is True
