import pytest
from app.v2.desktop.backend.rsi import RsiStart
from app.v2.desktop.backend.rsi_lint import RsiLintEnvironment, lint_binding


def test_lint_process_grant_requires_explicit_environment_and_target_tool(tmp_path):
    env = RsiLintEnvironment(root=str(tmp_path / "lint"), node=str(tmp_path / "node"))
    assert lint_binding(None, target=True, tools=["read_lints"])[1]["enabled"] is False
    assert lint_binding(env, target=False, tools=["read_lints"])[1]["enabled"] is False
    assert lint_binding(env, target=True, tools=["file_read"])[1]["enabled"] is False
    config, process = lint_binding(env, target=True, tools=["read_lints"])
    assert process["enabled"] and process["max_wall_time_seconds"] == 30
    assert process["allowed_executables"] == ["bash"]
    assert not process["allow_background_jobs"]
    assert str(tmp_path / "lint") in config["read_paths"]
    assert (
        RsiStart(
            goal="test", request_id="lint-test", lint_environment=env
        ).lint_environment
        == env
    )


def test_environment_requires_installation_and_hashes_changes(tmp_path):
    root = tmp_path / "lint"
    node = tmp_path / "node"
    node.write_text("node")
    node.chmod(0o755)
    env = RsiLintEnvironment(root=str(root), node=str(node))
    with pytest.raises(ValueError, match="not installed"):
        env.fingerprint()
    for name in [
        "bin/eslint",
        "eslint.config.mjs",
        "package-lock.json",
        "node_modules/eslint/package.json",
    ]:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    (root / "bin/eslint").chmod(0o755)
    before = env.fingerprint()
    (root / "eslint.config.mjs").write_text("changed")
    assert before != env.fingerprint()
    (root / "leak").symlink_to(node)
    with pytest.raises(ValueError, match="external file link"):
        env.fingerprint()


def test_relative_environment_paths_rejected():
    with pytest.raises(ValueError):
        RsiLintEnvironment(root="lint", node="/bin/node")


def test_standard_environment_is_selected_only_for_enabled_lint(monkeypatch, tmp_path):
    from app.v2.desktop.backend import rsi_lint

    env = RsiLintEnvironment(
        root=str(tmp_path / "standard"), node=str(tmp_path / "node")
    )
    calls = []

    def default():
        calls.append(True)
        return env

    monkeypatch.setattr(rsi_lint, "default_lint_environment", default)
    assert rsi_lint.resolve_lint_environment(None, ["file_read"]) is None
    assert calls == []
    assert rsi_lint.resolve_lint_environment(None, ["read_lints"]) == env
    assert len(calls) == 1
    assert rsi_lint.resolve_lint_environment(env, ["read_lints"]) == env
    assert len(calls) == 1
