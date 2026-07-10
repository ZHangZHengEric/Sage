from pathlib import Path

from common.core import config
from common.services.agent_workspace import cleanup_unselected_skills


def _server_cfg(tmp_path: Path) -> config.StartupConfig:
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
    Path(cfg.skill_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.user_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def _write_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\n---\n",
        encoding="utf-8",
    )
    return skill_dir


def test_cleanup_removes_only_deselected_managed_skills(tmp_path, monkeypatch):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    _write_skill(Path(cfg.skill_dir), "managed-skill")
    workspace_skills = Path(cfg.agents_dir) / "user_1" / "agent_1" / "skills"
    managed_skill = _write_skill(workspace_skills, "managed-skill")
    local_skill = _write_skill(workspace_skills, "local-skill")
    selected_skill = _write_skill(workspace_skills, "selected-skill")

    removed = cleanup_unselected_skills(
        "agent_1",
        {"availableSkills": ["selected-skill"]},
        previous_agent_config={
            "availableSkills": ["managed-skill", "local-skill", "selected-skill"]
        },
        user_id="user_1",
        app_mode="server",
    )

    assert removed == ["managed-skill"]
    assert not managed_skill.exists()
    assert local_skill.is_dir()
    assert selected_skill.is_dir()
