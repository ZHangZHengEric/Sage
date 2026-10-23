import json

import pytest

from sagents.v2.optimization import OptimizationConstraints
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from sagents.v2.optimization.package_workspace import (
    freeze_package, import_package, read_package, restore_authored_package, stage_package,
)
from tests.sagents.v2.test_package_optimizer import bundle


def test_authored_prompt_and_skill_are_exact_version_loaded_for_inference(tmp_path):
    parent = bundle()
    before = parent.model_dump_json()
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {"training-evidence/index.json": "{}"})
    (root / "package/files" / prompt).write_text("Convert units. Verify scale factors. Never send messages.")
    skill_path = root / "package/files/skills/verify-units/SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Verify units\nWhen converting, check dimension and scale; verify the result.")
    manifest_path = root / "package/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["agents"]["assistant"]["skills"] = ["verify-units"]
    manifest_path.write_text(json.dumps(manifest))
    patch, proposed = import_package(root, parent, "assistant", "Fix conversion mechanism", prompt)
    candidate = AgentPackageOptimizer._apply(parent, parent, "assistant", patch,
        OptimizationConstraints(allow_skill_changes=True, allow_skill_creation=True), "2")
    frozen = freeze_package(root, candidate, proposed, prompt, "assistant")
    assert read_package(root.parent / "version/package") == frozen
    assert frozen.content_hash == (root.parent / "version/package-hash.txt").read_text().strip()
    assert frozen.resolved_manifest().agents["assistant"].instructions.inline == (root / "package/files" / prompt).read_text()
    assert parent.model_dump_json() == before
    # Later edits to the draft cannot alter the version used by inference.
    (root / "package/files" / prompt).write_text("changed after freezing")
    assert read_package(root.parent / "version/package").content_hash == frozen.content_hash
    next_root, _ = stage_package(tmp_path, 2, frozen, "assistant", {})
    assert read_package(next_root / "package") == frozen


@pytest.mark.parametrize("field,value", [("mode", "specialist"), ("instructions", {"inline": "bypass path"})])
def test_manifest_edits_cannot_bypass_grant(tmp_path, field, value):
    parent = bundle()
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {})
    path = root / "package/manifest.json"
    data = json.loads(path.read_text())
    data["agents"]["assistant"][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        import_package(root, parent, "assistant", "ungranted", prompt)


def test_filesystem_bounds_and_ungranted_resources_rejected(tmp_path):
    parent = bundle()
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {})
    path = root / "package/files/secret.txt"
    path.write_text("ungranted resource")
    patch, _ = import_package(root, parent, "assistant", "new resource", prompt)
    with pytest.raises(ValueError, match="outside the allowlist"):
        AgentPackageOptimizer._apply(parent, parent, "assistant", patch, OptimizationConstraints(), "2")
    path.unlink()
    path.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlinks"):
        read_package(root / "package")


def test_deleted_resources_require_explicit_grant(tmp_path):
    parent = bundle()
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {})
    (root / "package/files/skills/units/SKILL.md").unlink()
    patch, _ = import_package(root, parent, "assistant", "Remove old procedure", prompt)
    with pytest.raises(ValueError, match="deletes files outside"):
        AgentPackageOptimizer._apply(parent, parent, "assistant", patch, OptimizationConstraints(), "2")
    candidate = AgentPackageOptimizer._apply(parent, parent, "assistant", patch,
        OptimizationConstraints(editable_files=("skills/units/SKILL.md",)), "2")
    assert "skills/units/SKILL.md" not in candidate.files


def test_completed_editor_snapshot_recovers_without_trusting_mutable_draft(tmp_path):
    parent = bundle()
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {})
    (root / "package/files" / prompt).write_text("Convert with dimensional checks. Never send messages.")
    saved = read_package(root / "package").model_dump(mode="json")
    stage_package(tmp_path, 1, parent, "assistant", {})  # Reset interrupted local writes.
    patch, proposed = import_package(root, parent, "assistant", "Completed recorded edit", prompt, snapshot=saved)
    assert patch.system_prompt == "Convert with dimensional checks. Never send messages."
    assert proposed.files[prompt] == patch.system_prompt
    restore_authored_package(root, saved)
    assert read_package(root / "package").model_dump(mode="json") == saved


def test_unchanged_inline_prompt_normalization_is_not_a_quality_proposal(tmp_path):
    from sagents.v2.optimization.optimizer import NoOptimizationChange
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["instructions"] = {"inline": "Convert units. Never send messages."}
    parent = type(bundle()).model_validate(data)
    root, prompt = stage_package(tmp_path, 1, parent, "assistant", {})
    patch, _ = import_package(root, parent, "assistant", "No justified change", prompt)
    with pytest.raises(NoOptimizationChange):
        AgentPackageOptimizer._apply(parent, parent, "assistant", patch, OptimizationConstraints(), "2")
