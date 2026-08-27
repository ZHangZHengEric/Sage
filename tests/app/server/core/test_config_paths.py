from pathlib import Path

from common.core import config


def test_server_defaults_store_runtime_data_under_sage_home(
    monkeypatch, tmp_path: Path
):
    home = tmp_path / "home"
    working_directory = tmp_path / "checkout"
    home.mkdir()
    working_directory.mkdir()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(working_directory)
    for env_name in (
        config.ENV.LOGS_DIR,
        config.ENV.SESSION_DIR,
        config.ENV.AGENTS_DIR,
        config.ENV.SKILL_DIR,
        config.ENV.USER_DIR,
        config.ENV.DB_FILE,
    ):
        monkeypatch.delenv(env_name, raising=False)

    cfg = config.build_startup_config("server")

    sage_home = home / ".sage"
    assert Path(cfg.logs_dir) == sage_home / "logs"
    assert Path(cfg.session_dir) == sage_home / "sessions"
    assert Path(cfg.agents_dir) == sage_home / "agents"
    assert Path(cfg.skill_dir) == sage_home / "skills"
    assert Path(cfg.user_dir) == sage_home / "users"
    assert Path(cfg.db_file) == sage_home / "sage.db"
    assert list(working_directory.iterdir()) == []
