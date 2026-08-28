from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock

import pytest

from sagents.utils.sandbox.providers.local.isolation import (
    bwrap as bwrap_module,
)
from sagents.utils.sandbox.providers.local.isolation import (
    seatbelt as seatbelt_module,
)
from sagents.utils.sandbox.providers.local.isolation import (
    subprocess as isolation_module,
)
from sagents.utils.sandbox.providers.local.isolation.bwrap import BwrapIsolation
from sagents.utils.sandbox.providers.local.isolation.seatbelt import (
    SeatbeltIsolation,
)
from sagents.utils.sandbox.providers.local.isolation.subprocess import (
    SubprocessIsolation,
)
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider


@pytest.mark.asyncio
async def test_subprocess_shell_runs_directly_and_honors_timeout(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        captured["env"] = kwargs["env"]
        return 7, "partial output", "no matches"

    monkeypatch.setattr(
        isolation_module,
        "run_with_streaming_stdout",
        fake_run,
    )
    monkeypatch.setattr(
        isolation_module,
        "_prepare_payload_files_sync",
        lambda *args, **kwargs: pytest.fail("shell execution must not use pickle"),
    )
    isolation = SubprocessIsolation(
        venv_dir=str(tmp_path / "venv"),
        sandbox_agent_workspace=str(tmp_path),
        sandbox_runtime_dir=str(tmp_path / "runtime"),
    )

    result = await isolation.execute(
        {"mode": "shell", "command": "ignored", "timeout_seconds": 0.25},
        cwd=str(tmp_path),
    )

    assert result == {
        "success": False,
        "output": "partial output",
        "stderr": "no matches",
        "return_code": 7,
    }
    assert captured["command"] == ["/bin/sh", "-c", "ignored"]
    assert captured["timeout"] == 0.25
    assert captured["env"]["PATH"].startswith(str(tmp_path / "venv" / "bin"))


@pytest.mark.asyncio
async def test_seatbelt_shell_runs_directly_without_pickle(tmp_path, monkeypatch):
    captured = {}
    profile_path = tmp_path / "shell.sb"
    profile_path.write_text("(version 1)", encoding="utf-8")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return 1, "", "no matches"

    monkeypatch.setattr(seatbelt_module, "run_with_streaming_stdout", fake_run)
    monkeypatch.setattr(
        seatbelt_module,
        "_prepare_payload_files_sync",
        lambda *args, **kwargs: pytest.fail("shell execution must not use pickle"),
    )
    isolation = SeatbeltIsolation(
        venv_dir=str(tmp_path / "venv"),
        sandbox_agent_workspace=str(tmp_path),
        sandbox_runtime_dir=str(tmp_path / "runtime"),
    )
    monkeypatch.setattr(
        isolation,
        "_generate_profile",
        lambda *args, **kwargs: str(profile_path),
    )

    result = await isolation.execute(
        {"mode": "shell", "command": "rg needle .", "timeout_seconds": 2},
        cwd=str(tmp_path),
    )

    assert result == {
        "success": False,
        "output": "",
        "stderr": "no matches",
        "return_code": 1,
    }
    assert captured["command"][-3:] == ["/bin/sh", "-c", "rg needle ."]
    assert captured["timeout"] == 2
    assert not profile_path.exists()


@pytest.mark.asyncio
async def test_bwrap_shell_runs_directly_without_pickle(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return 0, "match.py\n", ""

    monkeypatch.setattr(bwrap_module, "run_with_streaming_stdout", fake_run)
    monkeypatch.setattr(
        bwrap_module,
        "_prepare_payload_files_sync",
        lambda *args, **kwargs: pytest.fail("shell execution must not use pickle"),
    )
    isolation = BwrapIsolation(
        venv_dir=str(tmp_path / "venv"),
        sandbox_agent_workspace=str(tmp_path),
        sandbox_runtime_dir=str(tmp_path / "runtime"),
    )
    monkeypatch.setattr(
        isolation,
        "build_shell_command",
        lambda *args, **kwargs: ["bwrap", "/bin/sh", "-c", args[0]],
    )

    result = await isolation.execute(
        {"mode": "shell", "command": "rg needle .", "timeout_seconds": 3},
        cwd=str(tmp_path),
    )

    assert result == {
        "success": True,
        "output": "match.py\n",
        "stderr": "",
        "return_code": 0,
    }
    assert captured["command"] == ["bwrap", "/bin/sh", "-c", "rg needle ."]
    assert captured["timeout"] == 3


@pytest.mark.asyncio
async def test_local_provider_does_not_retry_after_isolation_timeout(
    tmp_path, monkeypatch
):
    class TimeoutIsolation:
        calls = 0

        async def execute(self, payload, cwd=None):
            self.calls += 1
            assert payload["timeout_seconds"] == 0.25
            raise subprocess.TimeoutExpired("grep", 0.25)

    provider = LocalSandboxProvider(
        sandbox_id="timeout-test",
        sandbox_agent_workspace=str(tmp_path),
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )
    isolation = TimeoutIsolation()
    provider._isolation = isolation
    monkeypatch.setattr(provider, "_ensure_initialized_async", AsyncMock())
    monkeypatch.setattr(provider, "_ensure_venv", AsyncMock())
    monkeypatch.setattr(provider, "to_host_path", lambda value: value)
    monkeypatch.setattr(
        provider, "_validate_host_path_allowed", lambda value, operation: value
    )
    monkeypatch.setattr(provider, "_get_server_bwrap_isolation", lambda: None)

    result = await provider.execute_command(
        "grep needle .",
        workdir=str(tmp_path),
        timeout=0.25,
    )

    assert isolation.calls == 1
    assert result.success is False
    assert result.return_code == -1
    assert result.stderr == "Command timed out after 0.25 seconds"


@pytest.mark.asyncio
async def test_local_provider_preserves_isolation_exit_details(tmp_path, monkeypatch):
    class CompletedIsolation:
        async def execute(self, payload, cwd=None):
            return {
                "success": False,
                "output": "partial output",
                "stderr": "no matches",
                "return_code": 7,
            }

    provider = LocalSandboxProvider(
        sandbox_id="exit-details-test",
        sandbox_agent_workspace=str(tmp_path),
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )
    provider._isolation = CompletedIsolation()
    monkeypatch.setattr(provider, "_ensure_initialized_async", AsyncMock())
    monkeypatch.setattr(provider, "_ensure_venv", AsyncMock())
    monkeypatch.setattr(provider, "to_host_path", lambda value: value)
    monkeypatch.setattr(
        provider, "_validate_host_path_allowed", lambda value, operation: value
    )
    monkeypatch.setattr(provider, "_get_server_bwrap_isolation", lambda: None)

    result = await provider.execute_command(
        "rg needle .",
        workdir=str(tmp_path),
        timeout=2,
    )

    assert result.success is False
    assert result.stdout == "partial output"
    assert result.stderr == "no matches"
    assert result.return_code == 7
