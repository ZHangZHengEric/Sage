"""HostBackgroundRunner 跨平台后台进程运行器单测。

仅依赖 Python stdlib + 主机 shell，POSIX 与 Windows 都应通过。
覆盖：start / read_tail / is_alive / get_exit_code / kill / cleanup。
"""
from __future__ import annotations

import os
import sys
import time

import pytest

from sagents.utils.sandbox._bg_runner import HostBackgroundRunner


pytestmark = pytest.mark.timeout(30)


def _python_q(s: str) -> str:
    """跨 shell 的 python 单行命令包装。

    POSIX 用 ``python3 -c '...'``；Windows 用 ``python -c "..."``。
    """
    if os.name == "nt":
        # Windows cmd 用双引号
        return f'python -c "{s}"'
    return f"python3 -c '{s}'"


@pytest.fixture
def runner(tmp_path):
    return HostBackgroundRunner(log_dir=str(tmp_path / "bg"))


def test_start_short_command_completes(runner):
    # 用 chr 拼字符串避免内嵌引号被 shell 吃掉
    info = runner.start(_python_q("import sys; sys.stdout.write(chr(104)+chr(105))"))
    task_id = info["task_id"]
    # 等待最多 5s
    deadline = time.time() + 5
    while time.time() < deadline and runner.is_alive(task_id):
        time.sleep(0.05)
    assert runner.is_alive(task_id) is False
    assert runner.get_exit_code(task_id) == 0
    assert "hi" in runner.read_tail(task_id)
    runner.cleanup(task_id)


def test_start_failing_command_reports_nonzero(runner):
    info = runner.start(_python_q("import sys; sys.exit(3)"))
    task_id = info["task_id"]
    deadline = time.time() + 5
    while time.time() < deadline and runner.is_alive(task_id):
        time.sleep(0.05)
    assert runner.get_exit_code(task_id) == 3
    runner.cleanup(task_id)


def test_kill_terminates_long_running_process(runner):
    # 跑一个 20s 的 python sleep；用 kill 干掉
    info = runner.start(_python_q("import time; time.sleep(20)"))
    task_id = info["task_id"]
    time.sleep(0.3)  # 让进程起来
    assert runner.is_alive(task_id) is True

    assert runner.kill(task_id, force=False) is True
    # 等到死
    deadline = time.time() + 5
    while time.time() < deadline and runner.is_alive(task_id):
        time.sleep(0.1)
    assert runner.is_alive(task_id) is False
    runner.cleanup(task_id)


def test_kill_force_after_terminate(runner):
    info = runner.start(_python_q("import time; time.sleep(20)"))
    task_id = info["task_id"]
    time.sleep(0.3)
    runner.kill(task_id, force=True)
    deadline = time.time() + 5
    while time.time() < deadline and runner.is_alive(task_id):
        time.sleep(0.1)
    assert runner.is_alive(task_id) is False
    runner.cleanup(task_id)


def test_unknown_task_id_returns_safe_defaults(runner):
    assert runner.read_tail("nope") == ""
    assert runner.is_alive("nope") is False
    assert runner.get_exit_code("nope") is None
    assert runner.kill("nope") is False
    runner.cleanup("nope")


def test_workdir_must_exist(runner, tmp_path):
    with pytest.raises(FileNotFoundError):
        runner.start("echo x", workdir=str(tmp_path / "does_not_exist"))


def test_log_file_lives_in_log_dir(runner):
    info = runner.start(_python_q("print('ok')"))
    assert info["log_path"].startswith(runner.log_dir)
    runner.cleanup(info["task_id"])
