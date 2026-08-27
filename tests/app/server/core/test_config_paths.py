from pathlib import Path

from common.core import config


def test_server_defaults_store_runtime_data_under_project_sage_directory(
    monkeypatch, tmp_path: Path
):
    home = tmp_path / "home"
    project_root = tmp_path / "checkout"
    working_directory = tmp_path / "launcher"
    home.mkdir()
    project_root.mkdir()
    working_directory.mkdir()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(config, "get_server_project_root", lambda: project_root)
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

    sage_home = project_root / ".sage"
    assert Path(cfg.logs_dir) == sage_home / "logs"
    assert Path(cfg.session_dir) == sage_home / "sessions"
    assert Path(cfg.agents_dir) == sage_home / "agents"
    assert Path(cfg.skill_dir) == sage_home / "skills"
    assert Path(cfg.user_dir) == sage_home / "users"
    assert Path(cfg.db_file) == sage_home / "sage.db"
    assert list(working_directory.iterdir()) == []


def test_server_main_initializes_logging_in_configured_directory(monkeypatch, tmp_path):
    from app.server import main as server_main

    cfg = config.StartupConfig(logs_dir=str(tmp_path / "configured-logs"))
    logging_calls = []

    monkeypatch.setattr(server_main.config, "init_startup_config", lambda: cfg)
    monkeypatch.setattr(
        server_main,
        "init_logging_base",
        lambda **kwargs: logging_calls.append(kwargs),
    )
    monkeypatch.setattr(server_main, "start_server", lambda current_cfg: None)

    assert server_main.main() == 0
    assert logging_calls[0]["log_path"] == cfg.logs_dir
