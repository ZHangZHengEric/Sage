import json
from pathlib import Path

import pytest

from app.v2.desktop.backend.rsi import RsiStore
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.settings_store import read_desktop_settings


def test_legacy_experiment_projects_migrate_by_record_identity_and_path(tmp_path: Path):
    store = RsiStore(tmp_path / "rsi.sqlite3")
    projects = [
        {"id": "internal", "name": "Renamed experiment", "path": str(tmp_path / "internal")},
        {"id": "external", "name": "RSI · external", "path": str(tmp_path / "external")},
        {"id": "manual", "name": "RSI · my own project", "path": str(tmp_path / "manual")},
        {"id": "explicit", "name": "Kept visible", "path": str(tmp_path / "explicit"), "source": "user"},
    ]
    store.put({"id": "rsi_internal", "status": "completed", "workspace_id": "internal"}, "user", "agent", "run")
    store.put({"id": "rsi_external", "status": "completed", "workspace_path": projects[1]["path"]}, "user", "agent", "run")
    store.put({"id": "rsi_explicit", "status": "completed", "workspace_id": "explicit"}, "user", "agent", "run")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"projects": projects}))
    settings = read_desktop_settings(settings_path)
    assert [p.source for p in settings.projects] == ["rsi", "rsi", "user", "user"]
    assert [p.path for p in settings.projects] == [p["path"] for p in projects]
    migrated = settings_path.read_bytes()
    assert read_desktop_settings(settings_path) == settings
    assert settings_path.read_bytes() == migrated
    assert len(store.list("user", "agent", "run")) == 3


@pytest.mark.asyncio
async def test_hidden_experiment_workspace_remains_accessible_and_can_be_added_manually(tmp_path):
    service = DesktopV2Service(tmp_path / "sage")
    workspace = tmp_path / "experiment/workspace"
    workspace.mkdir(parents=True)
    (workspace / "evidence.txt").write_text("Training evidence")
    try:
        project = await service.add_project("RSI · experiment", str(workspace), source="rsi")
        assert (await service.get_settings()).projects[0].source == "rsi"
        content, _ = await service.read_file(project.id, "sage", "evidence.txt")
        assert content == b"Training evidence"
        visible = await service.add_project("My experiment", str(workspace))
        assert visible.id == project.id
        assert (await service.get_settings()).projects[0].source == "user"
        assert (workspace / "evidence.txt").read_text() == "Training evidence"
    finally:
        await service.close()
