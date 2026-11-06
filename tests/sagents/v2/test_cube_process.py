from __future__ import annotations

import asyncio
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sagents.v2.runtime.execution.sandbox.plugins.cube.process import run_cube_process


class CommandSandbox:
    def __init__(self):
        self.commands = self

    def run(self, command, *, cwd, timeout):
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
        return SimpleNamespace(
            stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode
        )


@pytest.mark.asyncio
async def test_cube_process_preserves_argv_exit_code_and_bounds_output(tmp_path):
    result = await run_cube_process(
        CommandSandbox(),
        (
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1]); sys.exit(7)",
            "a; echo injected",
        ),
        cwd=str(tmp_path),
        env={},
        timeout=5,
        max_output_bytes=12,
    )
    assert result.exit_code == 7
    assert result.stdout == b"a; echo inje"
    assert result.truncated


@pytest.mark.asyncio
async def test_cube_cancellation_stops_the_remote_command_before_returning(tmp_path):
    marker = tmp_path / "late-write"
    task = asyncio.create_task(
        run_cube_process(
            CommandSandbox(),
            (
                sys.executable,
                "-c",
                "import pathlib,time; time.sleep(2); pathlib.Path('late-write').touch()",
            ),
            cwd=str(tmp_path),
            env={},
            timeout=10,
            max_output_bytes=1024,
        )
    )
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(2)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_cube_timeout_kills_descendants(tmp_path):
    marker = tmp_path / "late-write"
    result = await run_cube_process(
        CommandSandbox(),
        (
            sys.executable,
            "-c",
            "import subprocess,time; subprocess.Popen(['sh','-c','sleep 1; touch late-write']); time.sleep(5)",
        ),
        cwd=str(tmp_path),
        env={},
        timeout=0.2,
        max_output_bytes=1024,
    )
    assert result.exit_code != 0
    await asyncio.sleep(1.1)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_cube_timeout_still_applies_after_command_closes_output(tmp_path):
    marker = tmp_path / "late-write"
    result = await run_cube_process(
        CommandSandbox(),
        (
            sys.executable,
            "-c",
            "import os,pathlib,time; os.close(1); os.close(2); "
            "time.sleep(1); pathlib.Path('late-write').touch()",
        ),
        cwd=str(tmp_path),
        env={},
        timeout=0.2,
        max_output_bytes=1024,
    )
    assert result.exit_code != 0
    assert not marker.exists()
