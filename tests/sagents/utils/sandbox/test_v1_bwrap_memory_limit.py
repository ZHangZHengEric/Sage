"""v1 bwrap memory limits, including a bounded Linux allocation regression."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time

import pytest

from sagents.utils.sandbox._bg_runner import HostBackgroundRunner
from sagents.utils.sandbox.config import SandboxConfig
from sagents.utils.sandbox.providers.local.isolation import bwrap as module
from sagents.utils.sandbox.providers.local.isolation.bwrap import BwrapIsolation
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider


def isolation(tmp_path, memory_mb=64):
    return BwrapIsolation(
        venv_dir=str(tmp_path / "venv"),
        sandbox_agent_workspace=str(tmp_path),
        limits={"memory": memory_mb * 1024 * 1024},
    )


@pytest.mark.asyncio
async def test_env_limit_reaches_background_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_LOCAL_MEMORY_LIMIT_MB", "128")
    config = await SandboxConfig.from_env(sandbox_id="memory-test")
    sandbox = LocalSandboxProvider(
        sandbox_id="memory-test",
        sandbox_agent_workspace=str(tmp_path),
        memory_limit_mb=config.memory_limit_mb,
    )
    sandbox._init_isolation()
    # Explicitly select Linux isolation when running this test on macOS.
    if not isinstance(sandbox._isolation, BwrapIsolation):
        sandbox._isolation = isolation(tmp_path, config.memory_limit_mb)
    cmd = sandbox._isolation.build_shell_command(
        "python3 task.py",
        env_vars={"SAGE_LOCAL_MEMORY_LIMIT_MB": "999999", "PATH": str(tmp_path)},
    )
    assert cmd[-6:] == [
        "/usr/bin/prlimit", "--as=134217728:134217728", "--",
        "/bin/sh", "-c", "python3 task.py",
    ]


@pytest.mark.parametrize("memory", [0, -1, True, "4096", None])
def test_invalid_limit_rejected_before_launch(tmp_path, memory):
    sandbox = isolation(tmp_path)
    sandbox.limits["memory"] = memory
    with pytest.raises(ValueError, match="positive integer"):
        sandbox.build_shell_command("echo must-not-run")


@pytest.mark.asyncio
async def test_sync_shell_uses_limit(tmp_path, monkeypatch):
    captured = []

    def run(cmd, **kwargs):
        captured.extend(cmd)
        return 0, "ok", ""

    monkeypatch.setattr(module, "run_with_streaming_stdout", run)
    result = await isolation(tmp_path).execute({"mode": "shell", "command": "echo ok"})
    assert result["success"]
    assert captured[-6:] == [
        "/usr/bin/prlimit", "--as=67108864:67108864", "--",
        "/bin/sh", "-c", "echo ok",
    ]


@pytest.mark.asyncio
async def test_python_payload_uses_same_limit(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(module, "_prepare_payload_files_sync",
                        lambda *args: ("input", "output", "launcher"))
    monkeypatch.setattr(module, "_load_pickle_output_sync",
                        lambda *args: {"status": "success", "result": 42})
    monkeypatch.setattr(module, "_remove_file_if_exists_sync", lambda *args: None)

    def run(cmd, **kwargs):
        captured.extend(cmd)
        return 0, "", ""

    monkeypatch.setattr(module, "run_with_streaming_stdout", run)
    assert await isolation(tmp_path).execute({"mode": "python"}) == 42
    index = captured.index("/usr/bin/prlimit")
    assert captured[index:index + 3] == [
        "/usr/bin/prlimit", "--as=67108864:67108864", "--",
    ]
    assert captured[-3:] == ["launcher", "input", "output"]


LINUX = pytest.mark.skipif(
    sys.platform != "linux" or not os.path.exists("/usr/bin/prlimit"),
    reason="requires Linux util-linux prlimit",
)

# Bounded even if the regression reappears: at most 128 MiB, 10-second timeout.
# Check the kernel limit first so a broken wrapper never allocates unrestricted.
ALLOCATION_PROGRAM = """
import resource
assert resource.getrlimit(resource.RLIMIT_AS) == (67108864, 67108864)
blocks = []
try:
    for _ in range(128):
        blocks.append(bytearray(1024 * 1024))
except MemoryError:
    print('memory-limit-enforced', flush=True)
    raise SystemExit(42)
raise SystemExit('allocation unexpectedly succeeded')
"""


@LINUX
def test_linux_allocation_fails_without_affecting_parent(tmp_path):
    import resource

    before = resource.getrlimit(resource.RLIMIT_AS)
    cmd = isolation(tmp_path)._limit_command([sys.executable, "-c", ALLOCATION_PROGRAM])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 42, result.stderr
    assert "memory-limit-enforced" in result.stdout
    assert resource.getrlimit(resource.RLIMIT_AS) == before


@LINUX
def test_linux_background_shell_inherits_limit(tmp_path):
    runner = HostBackgroundRunner(log_dir=str(tmp_path / "logs"))
    shell = shlex.join([sys.executable, "-c", ALLOCATION_PROGRAM])
    cmd = isolation(tmp_path)._limit_command(["/bin/sh", "-c", shell])
    task = runner.start(cmd, shell=False)
    task_id = task["task_id"]
    try:
        deadline = time.monotonic() + 10
        while runner.is_alive(task_id) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not runner.is_alive(task_id)
        assert runner.get_exit_code(task_id) == 42
        assert "memory-limit-enforced" in runner.read_tail(task_id)
    finally:
        runner.cleanup(task_id)


@LINUX
def test_linux_child_cannot_raise_hard_limit(tmp_path):
    program = """
import resource
assert resource.getrlimit(resource.RLIMIT_AS) == (67108864, 67108864)
try:
    resource.setrlimit(resource.RLIMIT_AS, (134217728, 134217728))
except (ValueError, PermissionError):
    print('hard-limit-enforced')
else:
    raise SystemExit('hard limit unexpectedly raised')
"""
    cmd = isolation(tmp_path)._limit_command([
        "/bin/sh", "-c", shlex.join([sys.executable, "-c", program]),
    ])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "hard-limit-enforced" in result.stdout
