from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import pytest

from app.desktop_v2.backend.terminal import TerminalSessionManager


pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="the built-in PTY backend currently targets macOS and Linux",
)


@pytest.mark.asyncio
async def test_terminal_session_streams_real_pty_output_and_exit(tmp_path: Path):
    manager = TerminalSessionManager(shell_resolver=lambda: "/bin/sh")
    session = await manager.create(
        owner_id="user_1",
        cwd=tmp_path,
        columns=90,
        rows=24,
    )

    async def collect():
        return [event async for event in session.events()]

    events_task = asyncio.create_task(collect())
    await session.write(b"printf 'SAGE_PTY_OK\\n'\nexit 7\n")
    events = await asyncio.wait_for(events_task, timeout=5)

    output = b"".join(
        base64.b64decode(str(event["data"]))
        for event in events
        if event["type"] == "terminal.output"
    )
    exited = next(event for event in events if event["type"] == "terminal.exited")
    assert b"SAGE_PTY_OK" in output
    assert exited["exit_code"] == 7
    assert [int(event["sequence"]) for event in events] == list(
        range(1, len(events) + 1)
    )
    await manager.close()


@pytest.mark.asyncio
async def test_terminal_session_resizes_and_enforces_owner_scope(tmp_path: Path):
    manager = TerminalSessionManager(shell_resolver=lambda: "/bin/sh")
    session = await manager.create(
        owner_id="user_1",
        cwd=tmp_path,
        columns=80,
        rows=20,
    )

    await session.resize(120, 36)

    assert session.columns == 120
    assert session.rows == 36
    assert manager.get(session.session_id, "user_1") is session
    with pytest.raises(FileNotFoundError):
        manager.get(session.session_id, "user_2")
    await manager.close_session(session.session_id, "user_1")
    with pytest.raises(FileNotFoundError):
        manager.get(session.session_id, "user_1")


@pytest.mark.asyncio
async def test_terminal_rejects_invalid_dimensions(tmp_path: Path):
    manager = TerminalSessionManager(shell_resolver=lambda: "/bin/sh")

    with pytest.raises(ValueError, match="columns"):
        await manager.create(
            owner_id="user_1",
            cwd=tmp_path,
            columns=2,
            rows=20,
        )

    await manager.close()
