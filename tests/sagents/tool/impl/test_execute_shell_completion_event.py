"""execute_shell_command / await_shell 完成事件 + 自适应 + 去重 + GC 测试。

覆盖：
1. 后台命令完成时 watcher 写入事件，pop_completion_events 能取到，再次为空
2. await_shell 显式 completed 时事件被消费，pop_completion_events 取不到（去重）
3. 自适应改写：任务已跑 >30s 时，await_shell(block_until_ms<60s) 会被改写到 60s
4. 多 session 隔离：sid_A / sid_B 各自的事件互不串扰
5. pop_completion_events 不会误删 _BG_TASKS（system_reminder 路径）
6. 12h GC：超期 task 被 _gc_stale_tasks 强制清理
7. tail truncation：_truncate_tail_for_reminder 尾部优先截断
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import time

import pytest

from sagents.tool.impl.execute_command_tool import (
    ExecuteCommandTool,
    _suggest_next_block_ms,
    _truncate_tail_for_reminder,
    _BG_TASK_MAX_AGE_S,
)
from sagents.utils.sandbox.providers.passthrough.passthrough import PassthroughSandboxProvider


pytestmark = [
    pytest.mark.skipif(
        shutil.which("bash") is None,
        reason="需要 bash",
    ),
    pytest.mark.timeout(30),
]


@pytest.fixture
def shell_env(monkeypatch):
    tmpdir = tempfile.mkdtemp(prefix="sage_shell_evt_test_")
    sandbox = PassthroughSandboxProvider(sandbox_id="test", sandbox_agent_workspace=tmpdir)
    tool = ExecuteCommandTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)
    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    yield tool, sandbox, tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


async def _wait_event(session_id: str, task_id: str, timeout: float = 5.0) -> bool:
    """轮询直到指定 session+task_id 的事件出现，或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        bucket = ExecuteCommandTool._COMPLETION_EVENTS.get(session_id, {})
        if task_id in bucket:
            return True
        await asyncio.sleep(0.1)
    return False


# ---- 1. watcher 完成事件写入 ----

async def test_completion_event_emitted_after_finish(shell_env):
    tool, _, _ = shell_env
    started = await tool.execute_shell_command(
        command="sleep 0.3 && echo done",
        block_until_ms=0,
        session_id="sid_A",
    )
    assert started["status"] == "running"
    task_id = started["task_id"]

    # 等 watcher 写入事件
    appeared = await _wait_event("sid_A", task_id, timeout=5.0)
    assert appeared, "watcher 应在命令完成后写入 completion 事件"

    events = ExecuteCommandTool.pop_completion_events("sid_A")
    assert len(events) == 1
    ev = events[0]
    assert ev["task_id"] == task_id
    assert ev["exit_code"] == 0
    assert "done" in (ev.get("tail") or "")
    assert ev["elapsed_ms"] >= 0
    assert ev["command"] == "sleep 0.3 && echo done"

    # 再次 pop 应为空
    assert ExecuteCommandTool.pop_completion_events("sid_A") == []


# ---- 2. await_shell completed 时事件被消费（去重） ----

async def test_await_shell_consumes_completion_event(shell_env):
    tool, _, _ = shell_env
    started = await tool.execute_shell_command(
        command="sleep 0.3 && echo done",
        block_until_ms=0,
        session_id="sid_A",
    )
    task_id = started["task_id"]

    awaited = await tool.await_shell(task_id=task_id, block_until_ms=5000, session_id="sid_A")
    assert awaited["status"] == "completed"
    assert awaited["exit_code"] == 0

    # 等一会儿，给 watcher 充分时间（即便它后写入也会因 _BG_TASKS 已清而退出）
    await asyncio.sleep(0.5)

    # 消费过 / 或 watcher 因 task 已被 await_shell 清理而未写——两种情况都应该取不到事件
    assert ExecuteCommandTool.pop_completion_events("sid_A") == []


# ---- 3. 自适应改写 ----

async def test_await_shell_adaptive_rewrite_under_30s_block(shell_env, monkeypatch):
    """已运行 >30s 且传入 block_until_ms<60s 时，应被改写到 60s。
    用 monkeypatch 截获 _wait_for_finish 来直接观察传入值，不真正等待。"""
    tool, _, _ = shell_env
    started = await tool.execute_shell_command(
        command="sleep 60",
        block_until_ms=0,
        session_id="sid_A",
    )
    task_id = started["task_id"]
    ExecuteCommandTool._BG_TASKS[task_id]["started_at"] -= 35

    captured: dict = {}

    async def fake_wait(self, sandbox, info, block_until_ms, pattern=None):
        captured["block_until_ms"] = block_until_ms
        return False, None  # 强制 running

    monkeypatch.setattr(ExecuteCommandTool, "_wait_for_finish", fake_wait)

    out = await tool.await_shell(
        task_id=task_id,
        block_until_ms=200,
        session_id="sid_A",
    )

    assert out["status"] == "running"
    assert out["block_until_ms_requested"] == 200
    assert out["block_until_ms_used"] == 60_000
    assert captured["block_until_ms"] == 60_000
    assert out["running_for_ms"] >= 35_000
    assert out["suggested_next_block_ms"] >= 30_000

    await tool.kill_shell(task_id=task_id, session_id="sid_A")


def test_suggest_next_block_thresholds():
    assert _suggest_next_block_ms(0) == 60_000
    assert _suggest_next_block_ms(29_000) == 60_000
    assert _suggest_next_block_ms(60_000) == 90_000
    assert _suggest_next_block_ms(200_000) == 300_000
    assert _suggest_next_block_ms(400_000) == 600_000


# ---- 4. 多 session 隔离 ----

async def test_completion_events_session_isolated(shell_env):
    tool, _, _ = shell_env
    a = await tool.execute_shell_command(
        command="sleep 0.2 && echo A",
        block_until_ms=0,
        session_id="sid_A",
    )
    b = await tool.execute_shell_command(
        command="sleep 0.2 && echo B",
        block_until_ms=0,
        session_id="sid_B",
    )

    assert await _wait_event("sid_A", a["task_id"], timeout=5.0)
    assert await _wait_event("sid_B", b["task_id"], timeout=5.0)

    a_events = ExecuteCommandTool.pop_completion_events("sid_A")
    b_events = ExecuteCommandTool.pop_completion_events("sid_B")

    assert len(a_events) == 1 and a_events[0]["task_id"] == a["task_id"]
    assert "A" in (a_events[0].get("tail") or "")

    assert len(b_events) == 1 and b_events[0]["task_id"] == b["task_id"]
    assert "B" in (b_events[0].get("tail") or "")

    # 都应已清空
    assert ExecuteCommandTool.pop_completion_events("sid_A") == []
    assert ExecuteCommandTool.pop_completion_events("sid_B") == []


# ---- 5. await_shell 在 watcher 已写入事件后仍能正确返回 completed ----

async def test_await_shell_returns_completed_when_event_present(shell_env):
    """watcher 已写入事件、_BG_TASKS 仍保留时，await_shell 正常拿到 completed
    并消费事件（去重保护）。"""
    tool, _, _ = shell_env
    started = await tool.execute_shell_command(
        command="sleep 0.2 && echo via_event",
        block_until_ms=0,
        session_id="sid_A",
    )
    task_id = started["task_id"]

    appeared = await _wait_event("sid_A", task_id, timeout=5.0)
    assert appeared

    out = await tool.await_shell(task_id=task_id, block_until_ms=2000, session_id="sid_A")
    assert out["status"] == "completed"
    assert out["exit_code"] == 0
    assert "via_event" in out.get("stdout", "")

    # await_shell 显式消费掉了事件
    assert ExecuteCommandTool.pop_completion_events("sid_A") == []


# ---- 6. NOT_FOUND 兜底从事件取（task_info 已被消费方清理但事件仍残留的极少情况） ----

async def test_await_shell_not_found_falls_back_to_event(shell_env):
    """直接构造一个 task_info 不存在但事件存在的场景，
    验证 await_shell 兜底路径会消费该事件并返回 completed。"""
    tool, _, _ = shell_env
    fake_task_id = "shtask_zz_synth"
    ExecuteCommandTool._emit_completion_event(
        session_id="sid_A",
        task_id=fake_task_id,
        command="echo hi",
        exit_code=0,
        elapsed_ms=12,
        tail="hi\n",
    )
    out = await tool.await_shell(task_id=fake_task_id, block_until_ms=100, session_id="sid_A")
    assert out["status"] == "completed"
    assert out["exit_code"] == 0
    assert "hi" in out.get("stdout", "")
    assert ExecuteCommandTool.pop_completion_events("sid_A") == []


# ---- 7. system_reminder 消费（pop）不误删 _BG_TASKS ----

async def test_pop_events_does_not_remove_bg_task(shell_env):
    """pop_completion_events（system_reminder 路径）不应删除 _BG_TASKS 表项；
    之后 await_shell 仍能正常拿到 completed 结果。"""
    tool, _, _ = shell_env
    started = await tool.execute_shell_command(
        command="sleep 0.3 && echo remain",
        block_until_ms=0,
        session_id="sid_A",
    )
    task_id = started["task_id"]

    # 等 watcher 写入事件
    appeared = await _wait_event("sid_A", task_id, timeout=5.0)
    assert appeared

    # 模拟 system_reminder flush：只消费事件队列
    events = ExecuteCommandTool.pop_completion_events("sid_A")
    assert len(events) == 1

    # _BG_TASKS 应仍存在（watcher 故意不清理）
    assert task_id in ExecuteCommandTool._BG_TASKS

    # await_shell 仍能正常拿到 completed
    out = await tool.await_shell(task_id=task_id, block_until_ms=3000, session_id="sid_A")
    assert out["status"] == "completed"
    assert out["exit_code"] == 0
    assert "remain" in out.get("stdout", "")

    # await_shell 清理后 _BG_TASKS 应已删除
    assert task_id not in ExecuteCommandTool._BG_TASKS


# ---- 8. 12h GC：超期 task 被强制清理 ----

async def test_gc_stale_tasks_removes_expired_entries(shell_env):
    """_gc_stale_tasks 应删除超过 _BG_TASK_MAX_AGE_S 的 _BG_TASKS 与对应事件。"""
    tool, _, _ = shell_env

    # 直接手动注入一个超期 task（不真正起进程）
    stale_task_id = "shtask_stale_test"
    ExecuteCommandTool._BG_TASKS[stale_task_id] = {
        "task_id": stale_task_id,
        "session_id": "sid_stale",
        "pid": None,
        "log_path": None,
        "exit_path": None,
        "command": "echo stale",
        "started_at": time.time() - _BG_TASK_MAX_AGE_S - 10,
        "mode": "shell",
    }
    # 也注入对应事件
    ExecuteCommandTool._emit_completion_event(
        session_id="sid_stale",
        task_id=stale_task_id,
        command="echo stale",
        exit_code=0,
        elapsed_ms=999,
        tail="stale\n",
    )

    # 注入一个正常的（不该被 GC 的）
    fresh_task_id = "shtask_fresh_test"
    ExecuteCommandTool._BG_TASKS[fresh_task_id] = {
        "task_id": fresh_task_id,
        "session_id": "sid_fresh",
        "pid": None,
        "log_path": None,
        "exit_path": None,
        "command": "echo fresh",
        "started_at": time.time() - 60,   # 只跑了 60s，远未到 12h
        "mode": "shell",
    }

    # 触发 GC
    await tool._gc_stale_tasks()

    assert stale_task_id not in ExecuteCommandTool._BG_TASKS
    assert "sid_stale" not in ExecuteCommandTool._COMPLETION_EVENTS
    assert fresh_task_id in ExecuteCommandTool._BG_TASKS

    # 清理 fresh
    ExecuteCommandTool._BG_TASKS.pop(fresh_task_id, None)


# ---- 9. tail truncation ----

def test_truncate_tail_short_text_unchanged():
    text = "line1\nline2\n"
    assert _truncate_tail_for_reminder(text, max_bytes=512) == text


def test_truncate_tail_prefers_last_lines():
    lines = [f"line{i}" for i in range(200)]
    text = "\n".join(lines) + "\n"
    result = _truncate_tail_for_reminder(text, max_bytes=200)
    assert "line199" in result
    assert "line0" not in result
    assert result.startswith("...<truncated>...")


def test_truncate_tail_error_line_surfaced_when_tail_empty():
    """尾部全空行时，应从正文反向搜错误行并显示在头部。"""
    text = "some output\nERROR: something failed\nmore stuff\n\n\n\n"
    # max_bytes 只够截到尾部空行
    result = _truncate_tail_for_reminder(text, max_bytes=10)
    assert "[key line]" in result
    assert "ERROR" in result


def test_truncate_tail_no_false_error_line_when_tail_has_content():
    """尾部有实质内容时不应追加 [key line]，即使正文有 ERROR。"""
    text = "ERROR: something\n" + "x" * 200
    result = _truncate_tail_for_reminder(text, max_bytes=100)
    assert "[key line]" not in result
    assert result.startswith("...<truncated>...")


async def test_gc_also_triggered_in_await_shell(shell_env):
    """await_shell 入口也应触发 _gc_stale_tasks，清理超期 task。"""
    tool, _, _ = shell_env
    stale_id = "shtask_await_gc_test"
    ExecuteCommandTool._BG_TASKS[stale_id] = {
        "task_id": stale_id,
        "session_id": "sid_A",
        "pid": None,
        "log_path": None,
        "exit_path": None,
        "command": "echo stale",
        "started_at": time.time() - _BG_TASK_MAX_AGE_S - 1,
        "mode": "shell",
    }
    # await_shell 任意一个不存在的 task 来触发 GC
    await tool.await_shell(task_id="shtask_nonexistent_xyz", block_until_ms=100, session_id="sid_A")
    assert stale_id not in ExecuteCommandTool._BG_TASKS
