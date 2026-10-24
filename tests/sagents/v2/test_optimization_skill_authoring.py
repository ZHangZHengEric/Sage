"""Capability names survive authoring, renaming and immutable package sealing."""
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationConstraints, OptimizationPatch
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from sagents.v2.optimization.package_workspace import freeze_package, import_package, stage_package
from tests.sagents.v2.test_package_optimizer import bundle


NAME = "verify-eligible-variant-prices"
CONTENT = f"""---
name: {NAME}
description: Compare eligible variant prices when a user requests a price-based selection.
---
# Verify eligible variant prices
Read the user's constraints. Fetch eligible variants through the available catalog
tool, compare numeric prices, and verify the chosen variant satisfies the constraints.
Ask for missing constraints; stop if catalog results are unavailable.
"""
POLICY = OptimizationConstraints(allow_skill_changes=True, allow_skill_creation=True)


def apply(parent, patch, policy=POLICY):
    return AgentPackageOptimizer._apply(parent, parent, "assistant", patch, policy, "2")


def test_capability_named_skill_needs_no_fixed_host_candidate_and_seals_exactly(tmp_path):
    parent = bundle()
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {})
    skill = root / f"package/files/skills/{NAME}/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(CONTENT)
    manifest_path = root / "package/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["agents"]["assistant"]["skills"] = [NAME]
    manifest_path.write_text(json.dumps(manifest))
    (root / "package/files" / prompt).write_text(
        f"Do unit conversions. Never send messages. Load {NAME} using load_skill for price selection."
    )
    patch, authored = import_package(root, parent, "assistant", "Name the actual procedure", prompt)
    candidate = apply(parent, patch)
    frozen = freeze_package(root, candidate, authored, prompt, "assistant")
    assert frozen.files[f"skills/{NAME}/SKILL.md"] == CONTENT
    assert frozen.manifest.agents["assistant"].skills == (NAME,)
    assert NAME in frozen.resolved_manifest().agents["assistant"].instructions.inline
    assert f"skills/{NAME}/SKILL.md" not in parent.files


@pytest.mark.parametrize("workspace_style", [False, True])
@pytest.mark.parametrize("invalid,match", [
    (CONTENT.replace(f"name: {NAME}", "name: rsi-guidance"), "must match"),
    (CONTENT.replace("description: Compare eligible variant prices when a user requests a price-based selection.", "description: ''"), "description"),
    ("---\nname: example\n", "unterminated"),
    (CONTENT.replace(f"name: {NAME}", f"name: {NAME}\nname: other"), "invalid Skill"),
])
def test_declared_skill_identity_is_checked_for_both_patch_forms(workspace_style, invalid, match):
    values = {"files": {f"skills/{NAME}/SKILL.md": invalid}} if workspace_style else {
        "skill_definitions": {NAME: invalid}}
    with pytest.raises(ValueError, match=match):
        apply(bundle(), OptimizationPatch(rationale="Add capability", skills=(NAME,), **values))


def test_rename_updates_binding_and_preserves_original():
    data = bundle().model_dump(mode="json")
    old_path = "skills/rsi-guidance/SKILL.md"
    data["files"][old_path] = "Legacy capability instructions."
    data["manifest"]["agents"]["assistant"]["skills"] = ["rsi-guidance"]
    parent = type(bundle()).model_validate(data)
    values = dict(rationale="Rename to actual capability", deleted_files=(old_path,),
                  skill_definitions={NAME: CONTENT})
    with pytest.raises(ValueError, match="removed Skill still selected"):
        apply(parent, OptimizationPatch(**values))
    candidate = apply(parent, OptimizationPatch(skills=(NAME,), **values))
    assert candidate.manifest.agents["assistant"].skills == (NAME,)
    assert old_path not in candidate.files
    assert old_path in parent.files


def test_capability_naming_does_not_expand_creation_permissions():
    with pytest.raises(ValueError, match="creation is not enabled"):
        apply(bundle(), OptimizationPatch(rationale="Add capability", skill_definitions={NAME: CONTENT}),
              OptimizationConstraints(allow_skill_changes=True))


def test_new_skill_file_and_binding_are_admitted_in_one_patch():
    candidate = apply(bundle(), OptimizationPatch(
        rationale="Add a discoverable capability", skills=(NAME,),
        files={f"skills/{NAME}/SKILL.md": CONTENT},
    ))
    assert candidate.manifest.agents["assistant"].skills == (NAME,)
    assert candidate.files[f"skills/{NAME}/SKILL.md"] == CONTENT
