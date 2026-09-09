from __future__ import annotations

import asyncio
import os
import subprocess
import threading

from sagents.utils.sandbox.providers.local import local as local_module
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider


def test_concurrent_venv_initialization_does_not_block_event_loop(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    venv_dir = workspace / ".sandbox" / "venv"

    providers = [
        LocalSandboxProvider(
            sandbox_id=f"sandbox-{index}",
            sandbox_agent_workspace=str(workspace),
        )
        for index in range(2)
    ]
    for provider in providers:
        provider._venv_dir = str(venv_dir)

    creation_started = threading.Event()
    allow_creation_to_finish = threading.Event()

    def create_test_venv(*args, **kwargs):
        creation_started.set()
        assert allow_creation_to_finish.wait(timeout=0.5)
        os.makedirs(venv_dir / "bin", exist_ok=True)
        (venv_dir / "bin" / "python").touch()
        return subprocess.CompletedProcess(args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", create_test_venv)
    monkeypatch.setattr(local_module, "is_server_process", lambda: True)

    async def initialize_concurrently():
        first = asyncio.create_task(providers[0]._ensure_venv())
        assert await asyncio.to_thread(creation_started.wait, 0.5)

        timer = threading.Timer(0.1, allow_creation_to_finish.set)
        timer.start()
        try:
            second = asyncio.create_task(providers[1]._ensure_venv())
            await asyncio.sleep(0.02)
            assert not allow_creation_to_finish.is_set()
            await asyncio.gather(first, second)
        finally:
            allow_creation_to_finish.set()
            timer.join()

    asyncio.run(initialize_concurrently())
