from __future__ import annotations

import os

import pytest

from sagents.context.session_context import SessionContext
from sagents.utils.sandbox.environment import (
    DESKTOP_PROCESS_MARKER,
    SERVER_PROCESS_MARKER,
    build_agent_environment,
)
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider
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
        env_vars={"TASK_INPUT": "agent-visible"},
    )

    assert "--clearenv" in command
    assert "--unshare-pid" in command
    assert "must-not-leak" not in command
    assert command[-3:] == ["/bin/sh", "-c", "env"]
    task_input_index = command.index("TASK_INPUT")
    assert command[task_input_index + 1] == "agent-visible"


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
    assert "--clearenv" in captured["command"]
    assert "--unshare-pid" in captured["command"]
    assert captured["command"][-3:] == ["/bin/sh", "-c", "env"]
