from __future__ import annotations

import asyncio
import sys

from sagents.utils.sandbox.environment import SERVER_PROCESS_MARKER
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider
from sagents.utils.sandbox.providers.local.isolation.bwrap import BwrapIsolation


def _provider(tmp_path, *, linux_isolation_mode="subprocess"):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    provider = LocalSandboxProvider(
        sandbox_id="sandbox",
        sandbox_agent_workspace=str(workspace),
        linux_isolation_mode=linux_isolation_mode,
        macos_isolation_mode="subprocess",
    )
    provider._venv_dir = str(workspace / ".sandbox" / "venv")
    return provider


def test_server_does_not_install_uv_into_workspace_venv(monkeypatch, tmp_path):
    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    provider = _provider(tmp_path)

    monkeypatch.setattr(
        provider,
        "_get_venv_python",
        lambda: (_ for _ in ()).throw(AssertionError("server must skip workspace uv")),
    )

    asyncio.run(provider._ensure_uv_in_venv())


def test_non_server_keeps_workspace_uv_install_behavior(monkeypatch, tmp_path):
    monkeypatch.delenv(SERVER_PROCESS_MARKER, raising=False)
    provider = _provider(tmp_path)
    python_bin = tmp_path / "python"
    calls = []

    monkeypatch.setattr(provider, "_get_venv_python", lambda: str(python_bin))

    class Result:
        returncode = 0
        stderr = ""

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr("subprocess.run", run)

    asyncio.run(provider._ensure_uv_in_venv())

    assert calls[0][0][:5] == [
        str(python_bin),
        "-m",
        "pip",
        "install",
        "-U",
    ]
    assert calls[0][0][5] == "uv"


def test_local_provider_enables_output_cleanup_only_for_server(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")

    monkeypatch.setenv(SERVER_PROCESS_MARKER, "1")
    server_provider = _provider(
        tmp_path / "server", linux_isolation_mode="bwrap"
    )
    server_provider._init_isolation()

    monkeypatch.delenv(SERVER_PROCESS_MARKER, raising=False)
    desktop_provider = _provider(
        tmp_path / "desktop", linux_isolation_mode="bwrap"
    )
    desktop_provider._init_isolation()

    assert isinstance(server_provider._isolation, BwrapIsolation)
    assert server_provider._isolation.cleanup_output_payload is True
    assert isinstance(desktop_provider._isolation, BwrapIsolation)
    assert desktop_provider._isolation.cleanup_output_payload is False
