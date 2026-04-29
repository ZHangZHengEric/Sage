"""execute_shell_command / await_shell completed 分支返回 stdout 的完整 / 截断行为单测。

覆盖：
1. _read_completed_output：小文件返回完整内容、truncated=False
2. _read_completed_output：大文件返回尾部 + 显式截断标记 + truncated=True
3. _read_completed_output：shell-mode 兜底（无 native size 接口）走启发式路径
4. execute_shell_command 同步等到 completed，stdout / stdout_truncated / stdout_total_bytes 正确
5. execute_shell_command 命令输出 > 阈值时被显式截断
6. await_shell completed 也带回截断元信息
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time

import pytest

from sagents.tool.impl.execute_command_tool import (
    ExecuteCommandTool,
    _COMPLETED_STDOUT_MAX_BYTES,
)
from sagents.utils.sandbox.providers.passthrough.passthrough import PassthroughSandboxProvider


pytestmark = [
    pytest.mark.skipif(
        shutil.which("bash") is None,
        reason="需要 bash",
    ),
    pytest.mark.timeout(30),
]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def shell_env(monkeypatch):
    tmpdir = tempfile.mkdtemp(prefix="sage_shell_completed_test_")
    sandbox = PassthroughSandboxProvider(sandbox_id="test", sandbox_agent_workspace=tmpdir)
    tool = ExecuteCommandTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    yield tool, sandbox, tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_fake_task(tool, sandbox, log_path: str, mode: str = "native") -> dict:
    """伪造一个已完成任务的注册项，绕过真正的 spawn / wait。"""
    task_id = "shtask_fake_completed"
    task_info = {
        "task_id": task_id,
        "pid": -1,
        "log_path": log_path,
        "exit_path": None,
        "command": "fake",
        "started_at": time.time(),
        "mode": mode,
        "session_id": "sid_X",
    }
    ExecuteCommandTool._BG_TASKS[task_id] = task_info
    if mode == "native":
        # 把 fake task 注入 sandbox 内部 runner，使 read_background_output / size 能工作
        sandbox._bg_runner._tasks[task_id] = {
            "task_id": task_id,
            "pid": -1,
            "process": None,
            "log_path": log_path,
            "log_fh": None,
            "command": "fake",
            "started_at": time.time(),
        }
    return task_info


# ---- 1. _read_completed_output：小文件返回完整内容 ----

def test_read_completed_output_full_when_small(shell_env, tmp_path):
    tool, sandbox, _ = shell_env
    log = tmp_path / "small.log"
    log.write_bytes(b"hello world\n")
    task_info = _make_fake_task(tool, sandbox, str(log), mode="native")

    text, total, truncated = _run(tool._read_completed_output(sandbox, task_info))
    assert text == "hello world\n"
    assert total == len(b"hello world\n")
    assert truncated is False


# ---- 2. _read_completed_output：大文件截断 + 显式标记 ----

def test_read_completed_output_truncates_with_marker(shell_env, tmp_path, monkeypatch):
    tool, sandbox, _ = shell_env
    monkeypatch.setattr(
        "sagents.tool.impl.execute_command_tool._COMPLETED_STDOUT_MAX_BYTES",
        2048,
    )

    log = tmp_path / "big.log"
    lines = [f"row{i:05d}" for i in range(2000)]
    body = ("\n".join(lines) + "\n").encode("utf-8")
    assert len(body) > 2048
    log.write_bytes(body)
    task_info = _make_fake_task(tool, sandbox, str(log), mode="native")

    text, total, truncated = _run(tool._read_completed_output(sandbox, task_info, max_bytes=2048))
    assert truncated is True
    assert total == len(body)
    assert text.startswith("...<truncated: showing last ")
    assert "of " in text and "bytes" in text
    # 末尾几行必须保留
    assert "row01999" in text
    # 头部那条 row00000 不该在
    assert "row00000\n" not in text


# ---- 3. shell-mode 兜底：模拟 sandbox 没有 native size 接口 ----

def test_read_completed_output_shell_mode_falls_back_to_wc(shell_env, tmp_path, monkeypatch):
    """mode="shell" 时走 wc -c 取 size。这里直接 monkeypatch _shell 与 _read_tail。"""
    tool, sandbox, _ = shell_env
    monkeypatch.setattr(
        "sagents.tool.impl.execute_command_tool._COMPLETED_STDOUT_MAX_BYTES",
        100,
    )
    log_path = "/fake/path.log"
    body = "X" * 500

    async def fake_shell(self, sandbox, cmd, timeout=10):
        # wc -c < <path> 调用
        if "wc -c" in cmd:
            return 0, "500\n", ""
        return 0, "", ""

    async def fake_read_tail(self, sandbox, task_info, max_bytes=8192):
        # 模拟读 tail：返回最后 max_bytes 的 X
        return body[-max_bytes:]

    monkeypatch.setattr(ExecuteCommandTool, "_shell", fake_shell)
    monkeypatch.setattr(ExecuteCommandTool, "_read_tail", fake_read_tail)

    task_info = {
        "task_id": "shtask_fake_shell",
        "log_path": log_path,
        "mode": "shell",
        "started_at": time.time(),
    }
    text, total, truncated = _run(tool._read_completed_output(sandbox, task_info, max_bytes=100))
    assert total == 500
    assert truncated is True
    assert text.startswith("...<truncated: showing last 100 of 500 bytes")


def test_read_completed_output_size_unavailable_uses_heuristic(shell_env, monkeypatch):
    """size 取不到时，落回 "返回长度 == max_bytes 即视作截断" 的启发式。"""
    tool, sandbox, _ = shell_env

    async def no_size(self, sandbox, task_info):
        return None

    async def fake_read_tail(self, sandbox, task_info, max_bytes=8192):
        return "Y" * max_bytes  # 刚好填满

    monkeypatch.setattr(ExecuteCommandTool, "_read_log_size", no_size)
    monkeypatch.setattr(ExecuteCommandTool, "_read_tail", fake_read_tail)

    task_info = {"task_id": "tx", "log_path": "/x", "mode": "native", "started_at": time.time()}
    text, total, truncated = _run(tool._read_completed_output(sandbox, task_info, max_bytes=64))
    assert total is None
    assert truncated is True
    assert text.startswith("...<truncated: showing last ~64 bytes")


# ---- 4. 真实端到端：execute_shell_command 完成态返回字段 ----

def test_execute_shell_command_completed_returns_full_small_output(shell_env):
    tool, _, _ = shell_env
    out = _run(tool.execute_shell_command(
        command="printf hello",
        block_until_ms=10_000,
        session_id="sid_X",
    ))
    assert out["status"] == "completed"
    assert out["exit_code"] == 0
    assert out["stdout"] == "hello"
    assert out["stdout_truncated"] is False
    assert out["stdout_total_bytes"] == len(b"hello")


# ---- 5. 真实端到端：execute_shell_command 输出 > 阈值时被截断 ----

def test_execute_shell_command_completed_truncates_large_output(shell_env, monkeypatch):
    tool, _, _ = shell_env
    # 把阈值压到 2KB，方便构造
    monkeypatch.setattr(
        "sagents.tool.impl.execute_command_tool._COMPLETED_STDOUT_MAX_BYTES",
        2048,
    )
    # 5000 行 x ~10 字节 ≈ 50KB，远超 2KB
    cmd = (
        "python3 -c \"import sys\n"
        "for i in range(5000):\n"
        "    sys.stdout.write('row%05d\\n' % i)\""
    )
    out = _run(tool.execute_shell_command(
        command=cmd,
        block_until_ms=15_000,
        session_id="sid_X",
    ))
    assert out["status"] == "completed", out
    assert out["exit_code"] == 0
    assert out["stdout_truncated"] is True
    assert out["stdout_total_bytes"] is not None
    assert out["stdout_total_bytes"] > 2048
    assert out["stdout"].startswith("...<truncated: showing last ")
    assert "row04999" in out["stdout"]
    assert os.path.exists(out["output_file"])


# ---- 6. await_shell completed 分支也返回截断元信息 ----

def test_await_shell_completed_returns_truncation_fields(shell_env, monkeypatch):
    tool, _, _ = shell_env
    monkeypatch.setattr(
        "sagents.tool.impl.execute_command_tool._COMPLETED_STDOUT_MAX_BYTES",
        1024,
    )
    started = _run(tool.execute_shell_command(
        command="python3 -c \"print('z'*5000)\"",
        block_until_ms=0,
        session_id="sid_X",
    ))
    assert started["status"] == "running"
    task_id = started["task_id"]

    out = _run(tool.await_shell(task_id=task_id, block_until_ms=10_000, session_id="sid_X"))
    assert out["status"] == "completed"
    assert out["exit_code"] == 0
    assert out["stdout_truncated"] is True
    assert out["stdout_total_bytes"] >= 5000
    assert out["stdout"].startswith("...<truncated: showing last ")


def test_await_shell_completed_small_output_not_truncated(shell_env):
    tool, _, _ = shell_env
    started = _run(tool.execute_shell_command(
        command="printf ok",
        block_until_ms=0,
        session_id="sid_X",
    ))
    task_id = started["task_id"]
    out = _run(tool.await_shell(task_id=task_id, block_until_ms=5_000, session_id="sid_X"))
    assert out["status"] == "completed"
    assert out["stdout"] == "ok"
    assert out["stdout_truncated"] is False
    assert out["stdout_total_bytes"] == 2


# ---- 7. _COMPLETED_STDOUT_MAX_BYTES 默认值 sanity ----

def test_completed_stdout_default_threshold():
    assert _COMPLETED_STDOUT_MAX_BYTES == 1_000_000
