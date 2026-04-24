"""ToolProxy 强制注入与捆绑组测试。

覆盖：
- finish_turn 在白名单模式下被自动注入；
- {execute_shell_command, await_shell, kill_shell} 任意一个被勾选时三件套全部解锁。
"""
from __future__ import annotations

from sagents.tool.tool_base import tool
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy


class _StubShellTools:
    @tool()
    def execute_shell_command(self, command: str = ""):
        """run cmd"""
        return command

    @tool()
    def await_shell(self, task_id: str = ""):
        """wait cmd"""
        return task_id

    @tool()
    def kill_shell(self, task_id: str = ""):
        """kill cmd"""
        return task_id


class _StubFinishTurn:
    @tool()
    def finish_turn(self, reason: str = "task_done"):
        """finish"""
        return reason


def _build_proxy(available):
    tm = ToolManager(isolated=True, is_auto_discover=False)
    tm.register_tools_from_object(_StubShellTools())
    tm.register_tools_from_object(_StubFinishTurn())
    return ToolProxy(tool_managers=[tm], available_tools=available)


def test_finish_turn_force_injected_when_whitelist_set():
    proxy = _build_proxy(available=["execute_shell_command"])
    names = {t["name"] for t in proxy.list_tools()}
    assert "finish_turn" in names


def test_shell_bundle_unlocks_all_three_when_only_one_selected():
    proxy = _build_proxy(available=["execute_shell_command"])
    names = {t["name"] for t in proxy.list_tools()}
    assert {"execute_shell_command", "await_shell", "kill_shell"}.issubset(names)


def test_shell_bundle_triggered_by_await_shell_alone():
    proxy = _build_proxy(available=["await_shell"])
    names = {t["name"] for t in proxy.list_tools()}
    assert {"execute_shell_command", "await_shell", "kill_shell"}.issubset(names)


def test_no_bundle_when_none_selected():
    proxy = _build_proxy(available=[])
    names = {t["name"] for t in proxy.list_tools()}
    # 既没勾选 shell 任何一个，也不应自动出现
    assert "execute_shell_command" not in names
    assert "await_shell" not in names
    assert "kill_shell" not in names
    # 但 finish_turn 始终注入
    assert "finish_turn" in names
