from pathlib import Path

from common.core import config
from common.services import skill_service


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


def _write_skill(root: Path, dirname: str, name: str, description: str) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nBody\n",
        encoding="utf-8",
    )
    (skill_dir / "assets" / "nested").mkdir(parents=True)
    (skill_dir / "assets" / "nested" / "big.txt").write_text("x", encoding="utf-8")
    return skill_dir


def test_collect_server_skills_reads_metadata_without_file_tree(tmp_path, monkeypatch):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)
    skill_service._invalidate_server_skills_cache()

    _write_skill(Path(cfg.skill_dir), "system-dir", "system-skill", "System skill")
    _write_skill(
        Path(cfg.user_dir) / "user-a" / "skills", "user-dir", "user-skill", "User skill"
    )
    _write_skill(
        Path(cfg.agents_dir) / "user-a" / "agent-a" / "skills",
        "agent-dir",
        "agent-skill",
        "Agent skill",
    )

    skills = skill_service._collect_server_skills()

    assert {skill.name for skill in skills} == {
        "system-skill",
        "user-skill",
        "agent-skill",
    }
    assert all(skill.file_list == "" for skill in skills)


def test_collect_server_skills_cache_can_be_invalidated(tmp_path, monkeypatch):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)
    skill_service._invalidate_server_skills_cache()

    _write_skill(Path(cfg.skill_dir), "demo", "demo", "First")
    first = skill_service._collect_server_skills()
    assert first[0].description == "First"

    (Path(cfg.skill_dir) / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Second\n---\nBody\n",
        encoding="utf-8",
    )
    cached = skill_service._collect_server_skills()
    assert cached[0].description == "First"

    skill_service._invalidate_server_skills_cache()
    refreshed = skill_service._collect_server_skills()
    assert refreshed[0].description == "Second"


def test_collect_server_skills_scopes_private_skills_to_current_user(
    tmp_path, monkeypatch
):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)
    skill_service._invalidate_server_skills_cache()

    _write_skill(Path(cfg.skill_dir), "system-dir", "system-skill", "System skill")
    _write_skill(
        Path(cfg.user_dir) / "user-a" / "skills", "user-a-dir", "user-a-skill", "A"
    )
    _write_skill(
        Path(cfg.user_dir) / "user-b" / "skills", "user-b-dir", "user-b-skill", "B"
    )
    _write_skill(
        Path(cfg.agents_dir) / "user-a" / "agent-a" / "skills",
        "agent-a-dir",
        "agent-a-skill",
        "Agent A",
    )
    _write_skill(
        Path(cfg.agents_dir) / "user-b" / "agent-b" / "skills",
        "agent-b-dir",
        "agent-b-skill",
        "Agent B",
    )

    skills = skill_service._collect_server_skills(
        current_user_id="user-a",
        role="user",
    )

    assert {skill.name for skill in skills} == {
        "system-skill",
        "user-a-skill",
        "agent-a-skill",
    }
