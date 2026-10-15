from pathlib import Path

from app.v2.server.skills.workspaces import sync_workspaces
from app.v2.server.storage.paths import prepare_server_v2_storage


def test_sync_existing_agent_workspace_replaces_full_package(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    workspace = paths.workspace_dir("tenant-1", "writer/main")
    skill = workspace / "skills" / "guide"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("old\n")
    (skill / "extra.txt").write_text("old extra")
    cache = workspace / "skills" / ".catalog" / "guide" / "old"
    cache.mkdir(parents=True)
    (cache / "SKILL.md").write_text("cached\n")
    package = {"SKILL.md": b"new\n", "references/example.txt": b"reference\n"}

    result = sync_workspaces(tmp_path, "writer/main", {"guide": package})

    assert result["workspaces"] == 1
    assert result["changed_workspaces"] == 1
    assert (skill / "SKILL.md").read_bytes() == b"new\n"
    assert (skill / "references" / "example.txt").read_bytes() == b"reference\n"
    assert not (skill / "extra.txt").exists()
    assert (cache / "SKILL.md").read_text() == "cached\n"
    assert (Path(result["backup"]) / "tenant-1" / "guide" / "extra.txt").read_text() == "old extra"
    assert sync_workspaces(tmp_path, "writer/main", {"guide": package})["changed_workspaces"] == 0
