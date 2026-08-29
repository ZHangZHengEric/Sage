from __future__ import annotations

import os

import pytest

from sagents.context.session_context import SessionContext
from sagents.utils.sandbox.environment import (
    DESKTOP_PROCESS_MARKER,
    SERVER_PLAYWRIGHT_BROWSERS_PATH,
    SERVER_PROCESS_MARKER,
    build_agent_environment,
)
from sagents.utils.sandbox.providers.local import local as local_module
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider
from sagents.utils.sandbox.providers.local.isolation import bwrap as bwrap_module
from sagents.utils.sandbox.providers.local.isolation.bwrap import BwrapIsolation
from sagents.utils.sandbox.providers.passthrough.passthrough import (
    PassthroughSandboxProvider,
)


def test_server_agent_environment_uses_allowlist(tmp_path):
    env = build_agent_environment(
        home_dir=str(tmp_path),
        parent_env={
            SERVER_PROCESS_MARKER: "1",
            "PATH": "/bin",
            "LANG": "zh_CN.UTF-8",
            "SAGE_DEFAULT_LLM_API_KEY": "server-secret",
            "SAGE_MYSQL_PASSWORD": "database-secret",
        },
    )

    assert env["PATH"] == "/bin"
    assert env["LANG"] == "zh_CN.UTF-8"
    assert env["HOME"] == str(tmp_path)
    assert "SAGE_DEFAULT_LLM_API_KEY" not in env
    assert "SAGE_MYSQL_PASSWORD" not in env


def test_server_agent_environment_uses_fixed_global_playwright_browsers(tmp_path):
    env = build_agent_environment(
        {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path / "agent-cache")},
        home_dir=str(tmp_path),
        parent_env={
            SERVER_PROCESS_MARKER: "1",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    )

    assert env["PLAYWRIGHT_BROWSERS_PATH"] == SERVER_PLAYWRIGHT_BROWSERS_PATH


def test_explicit_tool_environment_is_forwarded(tmp_path):
    env = build_agent_environment(
        {"TASK_INPUT": "agent-visible"},
        home_dir=str(tmp_path),
        parent_env={"PATH": "/bin", "SAGE_SESSION_SECRET": "server-secret"},
    )

    assert env["TASK_INPUT"] == "agent-visible"
    assert "SAGE_SESSION_SECRET" not in env


def test_desktop_process_preserves_existing_environment():
    parent_env = {
        DESKTOP_PROCESS_MARKER: "1",
        "PATH": "/desktop/bin",
        "HOME": "/desktop/home",
        "DESKTOP_TOOL_SETTING": "keep-me",
    }

    env = build_agent_environment(
        home_dir="/ignored/agent/home",
        parent_env=parent_env,
    )

    assert env == parent_env
    assert env["HOME"] == "/desktop/home"


def test_server_environment_does_not_inherit_desktop_only_settings(tmp_path):
    env = build_agent_environment(
        home_dir=str(tmp_path),
        parent_env={
            DESKTOP_PROCESS_MARKER: "0",
            "PATH": os.defpath,
            "DESKTOP_TOOL_SETTING": "do-not-copy",
        },
    )

    assert DESKTOP_PROCESS_MARKER not in env
    assert "DESKTOP_TOOL_SETTING" not in env


def test_server_marker_overrides_desktop_marker(tmp_path):
    env = build_agent_environment(
        home_dir=str(tmp_path),
        parent_env={
            DESKTOP_PROCESS_MARKER: "1",
            SERVER_PROCESS_MARKER: "1",
            "PATH": "/bin",
            "SAGE_SESSION_SECRET": "server-secret",
        },
    )

    assert env["HOME"] == str(tmp_path)
    assert DESKTOP_PROCESS_MARKER not in env
    assert SERVER_PROCESS_MARKER not in env
    assert "SAGE_SESSION_SECRET" not in env


def test_bwrap_shell_uses_clean_environment_and_pid_namespace(monkeypatch, tmp_path):
    monkeypatch.delenv(DESKTOP_PROCESS_MARKER, raising=False)
    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    monkeypatch.setenv("SAGE_TEST_SERVER_SECRET", "must-not-leak")
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
    )

    command = isolation.build_shell_command(
        "env",
        cwd=str(workspace),
        env_vars={
            "TASK_INPUT": "agent-visible",
            "PATH": str(workspace),
            "LD_PRELOAD": str(workspace / "attack.so"),
        },
    )

    assert os.path.isabs(command[0])
    assert command[0].endswith("/bwrap")
    assert "--clearenv" in command
    assert "--unshare-pid" in command
    assert "must-not-leak" not in command
    assert command[-3:] == ["/bin/sh", "-c", "env"]
    task_input_index = command.index("TASK_INPUT")
    assert command[task_input_index + 1] == "agent-visible"


async def test_bwrap_supervisor_does_not_receive_agent_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    monkeypatch.delenv(DESKTOP_PROCESS_MARKER, raising=False)
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
    )
    captured = {}
    info_messages = []
    error_messages = []

    def run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return 0, "", ""

    monkeypatch.setattr(bwrap_module, "run_with_streaming_stdout", run)
    monkeypatch.setattr(bwrap_module.logger, "info", info_messages.append)
    monkeypatch.setattr(bwrap_module.logger, "error", error_messages.append)

    result = await isolation.execute(
        {
            "mode": "shell",
            "command": "env",
            "env_vars": {
                "PATH": str(workspace),
                "LD_PRELOAD": str(workspace / "attack.so"),
            },
        },
        cwd=str(workspace),
    )

    assert result == {
        "success": True,
        "output": "",
        "stderr": "",
        "return_code": 0,
    }
    assert os.path.isabs(captured["command"][0])
    assert captured["env"]["PATH"] != str(workspace)
    assert "LD_PRELOAD" not in captured["env"]
    assert "LD_PRELOAD" in captured["command"]
    assert info_messages == [
        "[BwrapIsolation] 执行完成: command='env', return_code=0"
    ]
    assert error_messages == []


async def test_server_bwrap_removes_input_and_output_payloads(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
        cleanup_output_payload=True,
    )
    removed = []

    monkeypatch.setattr(
        bwrap_module,
        "_prepare_payload_files_sync",
        lambda *args: ("input.pkl", "output.pkl", "launcher.py"),
    )
    monkeypatch.setattr(
        bwrap_module,
        "_load_pickle_output_sync",
        lambda path: {"status": "success", "result": "ok"},
    )
    monkeypatch.setattr(
        bwrap_module,
        "_remove_file_if_exists_sync",
        removed.append,
    )
    monkeypatch.setattr(
        bwrap_module,
        "run_with_streaming_stdout",
        lambda *args, **kwargs: (0, "", ""),
    )

    result = await isolation.execute(
        {"mode": "python", "command": "true", "env_vars": {}},
        cwd=str(workspace),
    )

    assert result == "ok"
    assert removed == ["input.pkl", "output.pkl"]


async def test_default_bwrap_preserves_output_payload_for_non_server_callers(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
    )
    removed = []

    monkeypatch.setattr(
        bwrap_module,
        "_prepare_payload_files_sync",
        lambda *args: ("input.pkl", "output.pkl", "launcher.py"),
    )
    monkeypatch.setattr(
        bwrap_module,
        "_load_pickle_output_sync",
        lambda path: {"status": "success", "result": "ok"},
    )
    monkeypatch.setattr(
        bwrap_module,
        "_remove_file_if_exists_sync",
        removed.append,
    )
    monkeypatch.setattr(
        bwrap_module,
        "run_with_streaming_stdout",
        lambda *args, **kwargs: (0, "", ""),
    )

    await isolation.execute(
        {"mode": "python", "command": "true", "env_vars": {}},
        cwd=str(workspace),
    )

    assert removed == ["input.pkl"]


async def test_server_bwrap_removes_output_payload_after_execution_failure(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
        cleanup_output_payload=True,
    )
    removed = []
    info_messages = []
    error_messages = []

    monkeypatch.setattr(
        bwrap_module,
        "_prepare_payload_files_sync",
        lambda *args: ("input.pkl", "output.pkl", "launcher.py"),
    )
    monkeypatch.setattr(
        bwrap_module,
        "_remove_file_if_exists_sync",
        removed.append,
    )
    monkeypatch.setattr(
        bwrap_module,
        "run_with_streaming_stdout",
        lambda *args, **kwargs: (1, "", "failed"),
    )
    monkeypatch.setattr(bwrap_module.logger, "info", info_messages.append)
    monkeypatch.setattr(bwrap_module.logger, "error", error_messages.append)

    with pytest.raises(Exception, match="Bwrap execution failed"):
        await isolation.execute(
            {"mode": "python", "command": "false", "env_vars": {}},
            cwd=str(workspace),
        )

    assert removed == ["input.pkl", "output.pkl"]
    assert info_messages == []
    assert error_messages == [
        "[BwrapIsolation] 执行失败: command='false', return_code=1, "
        "error=Bwrap execution failed: failed"
    ]


async def test_bwrap_payload_failure_logs_once(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
        cleanup_output_payload=True,
    )
    info_messages = []
    error_messages = []

    monkeypatch.setattr(
        bwrap_module,
        "_prepare_payload_files_sync",
        lambda *args: ("input.pkl", "output.pkl", "launcher.py"),
    )
    monkeypatch.setattr(
        bwrap_module,
        "_load_pickle_output_sync",
        lambda path: {"status": "error", "error": "Command failed with code 127"},
    )
    monkeypatch.setattr(
        bwrap_module,
        "_remove_file_if_exists_sync",
        lambda path: None,
    )
    monkeypatch.setattr(
        bwrap_module,
        "run_with_streaming_stdout",
        lambda *args, **kwargs: (0, "", ""),
    )
    monkeypatch.setattr(bwrap_module.logger, "info", info_messages.append)
    monkeypatch.setattr(bwrap_module.logger, "error", error_messages.append)

    with pytest.raises(Exception, match="Command failed with code 127"):
        await isolation.execute(
            {"mode": "python", "command": "missing-command", "env_vars": {}},
            cwd=str(workspace),
        )

    assert info_messages == []
    assert error_messages == [
        "[BwrapIsolation] 执行失败: command='missing-command', return_code=0, "
        "error=Error in bwrap: Command failed with code 127"
    ]


async def test_server_isolation_failure_does_not_repeat_bwrap_error(
    monkeypatch, tmp_path
):
    class FailingIsolation:
        async def execute(self, payload, cwd=None):
            raise Exception("Error in bwrap: Command failed with code 127")

    provider = LocalSandboxProvider(
        sandbox_id="sandbox",
        sandbox_agent_workspace=str(tmp_path),
    )
    provider._isolation = FailingIsolation()
    error_messages = []

    async def noop():
        return None

    monkeypatch.setattr(provider, "_ensure_initialized_async", noop)
    monkeypatch.setattr(provider, "_ensure_venv", noop)
    monkeypatch.setattr(provider, "_get_venv_python", lambda: None)
    monkeypatch.setattr(
        provider, "_get_server_bwrap_isolation", lambda: provider._isolation
    )
    monkeypatch.setattr(local_module.logger, "error", error_messages.append)

    result = await provider.execute_command("missing-command", workdir=str(tmp_path))

    assert result.success is False
    assert result.return_code == -1
    assert error_messages == []


async def test_server_rejects_passthrough_mode(monkeypatch, tmp_path):
    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    monkeypatch.delenv(DESKTOP_PROCESS_MARKER, raising=False)
    monkeypatch.setenv("SAGE_SANDBOX_MODE", "passthrough")
    context = SessionContext(
        session_id="session",
        user_id="user",
        agent_id="agent",
        session_root_space=str(tmp_path),
    )

    with pytest.raises(RuntimeError, match="cannot use passthrough"):
        await context.init_more()


async def test_passthrough_provider_fails_closed_in_server(monkeypatch, tmp_path):
    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    monkeypatch.delenv(DESKTOP_PROCESS_MARKER, raising=False)
    provider = PassthroughSandboxProvider(
        sandbox_id="sandbox",
        sandbox_agent_workspace=str(tmp_path),
    )

    with pytest.raises(RuntimeError, match="cannot initialize passthrough"):
        await provider.initialize()


async def test_desktop_passthrough_provider_still_initializes(monkeypatch, tmp_path):
    monkeypatch.delenv(SERVER_PROCESS_MARKER, raising=False)
    monkeypatch.setenv(DESKTOP_PROCESS_MARKER, "1")
    provider = PassthroughSandboxProvider(
        sandbox_id="sandbox",
        sandbox_agent_workspace=str(tmp_path),
    )

    await provider.initialize()

    assert provider.workspace_path == str(tmp_path)


async def test_server_local_background_command_is_wrapped_by_bwrap(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    monkeypatch.delenv(DESKTOP_PROCESS_MARKER, raising=False)
    workspace = tmp_path / "workspace"
    runtime = workspace / ".sandbox"
    workspace.mkdir()
    runtime.mkdir()
    provider = LocalSandboxProvider(
        sandbox_id="sandbox",
        sandbox_agent_workspace=str(workspace),
        linux_isolation_mode="bwrap",
    )
    provider._isolation = BwrapIsolation(
        venv_dir=str(workspace / ".venv"),
        sandbox_agent_workspace=str(workspace),
        sandbox_runtime_dir=str(runtime),
    )

    async def initialized():
        return None

    captured = {}

    def start(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return {"task_id": "task", "pid": 1, "log_path": "log"}

    monkeypatch.setattr(provider, "_ensure_initialized_async", initialized)
    monkeypatch.setattr(provider._bg_runner, "start", start)

    await provider.start_background(
        "env",
        workdir=str(workspace),
        env_vars={"TASK_INPUT": "agent-visible"},
    )

    assert captured["shell"] is False
    assert captured["env_vars"] is None
    assert os.path.isabs(captured["command"][0])
    assert "--clearenv" in captured["command"]
    assert "--unshare-pid" in captured["command"]
    assert captured["command"][-3:] == ["/bin/sh", "-c", "env"]
