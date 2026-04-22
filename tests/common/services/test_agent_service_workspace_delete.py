import asyncio
from pathlib import Path

from common.core import config
from common.services import agent_service


def _build_cfg(tmp_path: Path) -> config.StartupConfig:
    root = tmp_path / "sage"
    cfg = config.StartupConfig(
        app_mode="server",
        logs_dir=str(root / "logs"),
        session_dir=str(root / "sessions"),
        agents_dir=str(root / "agents"),
        skill_dir=str(root / "skills"),
        user_dir=str(root / "users"),
    )
    Path(cfg.agents_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def test_delete_server_agent_workspace_deletes_existing_workspace(tmp_path, monkeypatch):
    cfg = _build_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    workspace = Path(cfg.agents_dir) / "user_a" / "agent_demo"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "artifact.txt").write_text("hello", encoding="utf-8")

    result = asyncio.run(
        agent_service.delete_server_agent_workspace("agent_demo", "user_a")
    )

    assert result["deleted"] is True
    assert result["agent_id"] == "agent_demo"
    assert result["user_id"] == "user_a"
    assert not workspace.exists()


def test_delete_server_agent_workspace_returns_false_when_missing(tmp_path, monkeypatch):
    cfg = _build_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    result = asyncio.run(
        agent_service.delete_server_agent_workspace("agent_demo", "user_a")
    )

    assert result["deleted"] is False
    assert result["agent_id"] == "agent_demo"
    assert result["user_id"] == "user_a"


def test_delete_agent_workspace_on_host_desktop_removes_tree(tmp_path, monkeypatch):
    agents_root = tmp_path / "agents_mount"
    agents_root.mkdir()
    monkeypatch.setenv("SAGE_AGENTS_PATH", str(agents_root))
    cfg = config.StartupConfig(
        app_mode="desktop",
        logs_dir=str(tmp_path / "logs"),
        session_dir=str(tmp_path / "sessions"),
        agents_dir=str(tmp_path / "agents_unused"),
        skill_dir=str(tmp_path / "skills"),
        user_dir=str(tmp_path / "users"),
    )
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    ws = agents_root / "agent_desktop"
    ws.mkdir()
    (ws / "x.txt").write_text("z", encoding="utf-8")

    result = agent_service.delete_agent_workspace_on_host("agent_desktop", "")

    assert result["deleted"] is True
    assert not ws.exists()
