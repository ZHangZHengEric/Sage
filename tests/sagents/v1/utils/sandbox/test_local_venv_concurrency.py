from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from contextlib import contextmanager

import pytest

from sagents.v1.utils.sandbox.providers.local import local as local_module
from sagents.v1.utils.sandbox.providers.local.local import LocalSandboxProvider


@pytest.mark.timeout(15)
@pytest.mark.skipif(os.name == "nt", reason="file_lock uses flock only on POSIX")
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

    allow_creation_to_finish = threading.Event()
    creation_count = 0
    original_file_lock = local_module.file_lock

    def create_test_venv(*args, **kwargs):
        nonlocal creation_count
        assert threading.get_ident() != loop_thread
        creation_count += 1
        loop.call_soon_threadsafe(creation_started.set)
        assert allow_creation_to_finish.wait(timeout=5)
        os.makedirs(venv_dir / "bin", exist_ok=True)
        (venv_dir / "bin" / "python").touch()
        return subprocess.CompletedProcess(args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", create_test_venv)
    monkeypatch.setattr(local_module, "is_server_process", lambda: True)

    async def initialize_concurrently():
        nonlocal loop, loop_thread, creation_started
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        creation_started = asyncio.Event()
        second_lock_attempted = asyncio.Event()
        attempts_lock = threading.Lock()
        lock_attempts = 0

        @contextmanager
        def checked_file_lock(path):
            nonlocal lock_attempts
            # Fail before acquiring a blocking lock if offloading regresses.
            assert threading.get_ident() != loop_thread
            with attempts_lock:
                lock_attempts += 1
                if lock_attempts == 2:
                    loop.call_soon_threadsafe(second_lock_attempted.set)
            with original_file_lock(path):
                yield

        monkeypatch.setattr(local_module, "file_lock", checked_file_lock)
        tasks = [asyncio.create_task(providers[0]._ensure_venv())]
        tasks[0].add_done_callback(lambda _: creation_started.set())
        try:
            await asyncio.wait_for(creation_started.wait(), timeout=5)
            if tasks[0].done():
                tasks[0].result()
            tasks.append(asyncio.create_task(providers[1]._ensure_venv()))
            tasks[1].add_done_callback(lambda _: second_lock_attempted.set())
            await asyncio.wait_for(second_lock_attempted.wait(), timeout=5)
            if tasks[1].done():
                tasks[1].result()
            # Only this coroutine releases creation, after both workers reached
            # the critical section. No wall-clock race decides correctness.
            assert not allow_creation_to_finish.is_set()
            assert all(not task.done() for task in tasks)
            allow_creation_to_finish.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
            assert lock_attempts == 2
            assert creation_count == 1
        finally:
            allow_creation_to_finish.set()
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=5
            )

    loop = None
    loop_thread = None
    creation_started = None
    asyncio.run(initialize_concurrently())
