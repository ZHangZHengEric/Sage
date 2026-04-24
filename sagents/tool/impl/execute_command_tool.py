#!/usr/bin/env python3
"""
Execute Command Tool

通过沙箱执行命令的工具，所有命令都在沙箱环境中运行。

新版本支持两段式：
- ``execute_shell_command(command, ..., block_until_ms=30000)``
  - ``block_until_ms == 0`` 立即放后台，返回 ``task_id`` 与输出文件路径；
  - ``block_until_ms > 0`` 阻塞等待至命令完成或到点，到点未结束返回 ``task_id`` + tail 输出。
- ``await_shell(task_id, block_until_ms=10000, pattern=None)`` 拉取增量输出，结束后返回 ``exit_code``。
- ``kill_shell(task_id)`` 发 SIGTERM，再视情况升级 SIGKILL。
"""

from __future__ import annotations

import asyncio
import json as _json
import re
import shlex
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..tool_base import tool
from ..error_codes import ToolErrorCode, make_tool_error
from sagents.utils.logger import logger
from sagents.utils.sandbox._stdout_echo import echo_header, echo_footer
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util


_BG_DIR = "~/.sage/bg"


class SecurityManager:
    """安全管理器 - 负责命令安全检查。

    黑名单同时做：
    1. 命令名前缀匹配（base command 在 ``DANGEROUS_COMMANDS`` 中）。
    2. 高危子串匹配（``DANGEROUS_SUBSTRINGS``，如 ``rm -rf /``、``git push --force`` 等）。
    3. 管道下载执行检测（``curl ... | sh`` / ``wget ... | bash``）。
    """

    DANGEROUS_COMMANDS = {
        # 文件系统破坏 / 分区
        'format', 'fdisk', 'mkfs', 'parted', 'wipefs',
        # 提权 / 账户
        'sudo', 'su', 'passwd', 'visudo', 'useradd', 'userdel', 'usermod',
        # 系统状态
        'shutdown', 'reboot', 'halt', 'poweroff', 'init',
        'systemctl', 'service',
        # 直接写盘 / 调度
        'dd', 'crontab', 'at', 'batch',
        # 内核/驱动
        'insmod', 'rmmod', 'modprobe',
    }

    DANGEROUS_SUBSTRINGS = (
        'rm -rf /',
        'rm -rf /*',
        'rm -rf ~',
        ':() { :|:& };:',          # fork bomb
        'mkfs.',
        'chmod 777 /',
        'chown -r root',
        'mv / ',
        'mv /* ',
        '> /dev/sda',
        '> /dev/sdb',
        '> /dev/nvme',
        'git push --force',
        'git push -f ',
        'git push --force-with-lease origin main',
        'git push --force-with-lease origin master',
        'git reset --hard origin',
    )

    # 管道下载 + 直接执行的常见模式
    _PIPE_EXEC_RE = re.compile(
        r'\b(curl|wget|fetch)\b[^|;&]+?\|\s*(sudo\s+)?(ba)?sh\b',
        re.IGNORECASE,
    )

    def is_command_safe(self, command: str) -> Tuple[bool, str]:
        if not command or not command.strip():
            return False, "命令不能为空"

        original = command.strip()
        lowered = original.lower()

        # 子串匹配
        for sub in self.DANGEROUS_SUBSTRINGS:
            if sub in lowered:
                return False, f"危险命令被阻止（含子串 {sub!r}）"

        # 管道 sh
        if self._PIPE_EXEC_RE.search(original):
            return False, "危险命令被阻止：检测到 curl/wget ... | sh 类下载即执行模式"

        # 命令名前缀（按管道/分号切分逐段检查）
        for segment in re.split(r'[|;&]+', lowered):
            parts = segment.strip().split()
            if not parts:
                continue
            base = parts[0].split('/')[-1]
            if base in self.DANGEROUS_COMMANDS or base.startswith('mkfs.'):
                return False, f"危险命令被阻止: {base}"

        return True, "命令安全检查通过"


def _gen_task_id() -> str:
    return "shtask_" + uuid.uuid4().hex[:12]


class ExecuteCommandTool:
    """命令执行工具 - 通过沙箱执行命令。两段式 + 后台进程注册表。"""

    # 进程级注册表：task_id -> {session_id, pid, log_path, exit_path, command, started_at}
    _BG_TASKS: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        self.security_manager = SecurityManager()

    def _get_sandbox(self, session_id: str):
        return _get_session_sandbox_util(session_id, log_prefix="ExecuteCommandTool")

    @staticmethod
    def _parse_env_vars(env_vars: Any) -> Optional[Dict[str, str]]:
        if env_vars is None:
            return None
        if isinstance(env_vars, dict):
            return env_vars
        if isinstance(env_vars, str) and env_vars.strip():
            try:
                return _json.loads(env_vars)
            except Exception:
                logger.warning(f"env_vars 解析失败，忽略: {env_vars!r}")
        return None

    async def _shell(self, sandbox: Any, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        try:
            r = await sandbox.execute_command(command=cmd, timeout=timeout)
            return (
                int(getattr(r, "return_code", -1) or 0),
                getattr(r, "stdout", "") or "",
                getattr(r, "stderr", "") or "",
            )
        except Exception as exc:
            return -1, "", str(exc)

    @staticmethod
    def _sandbox_supports_native_bg(sandbox: Any) -> bool:
        try:
            return bool(sandbox.supports_background())
        except Exception:
            return False

    async def _spawn_background(
        self,
        sandbox: Any,
        command: str,
        workdir: Optional[str],
        env_vars: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        """在沙箱内后台启动命令。

        优先调用沙箱原生 ``start_background``（PassthroughSandbox / LocalSandbox 已实现，
        跨 POSIX/Windows）；缺失时回退到 bash-shell 包装（仅 POSIX 沙箱可用，
        例如远程 Linux 容器）。

        返回 task_info（含 task_id / pid / log_path / mode）。
        """
        # === 1) 原生路径（跨平台） ===
        if self._sandbox_supports_native_bg(sandbox):
            info = await sandbox.start_background(command, workdir=workdir, env_vars=env_vars)
            task_id = info["task_id"]
            task_info = {
                "task_id": task_id,
                "pid": info.get("pid"),
                "log_path": info.get("log_path"),
                "exit_path": None,
                "command": command,
                "started_at": time.time(),
                "mode": "native",
            }
            ExecuteCommandTool._BG_TASKS[task_id] = task_info
            return task_info

        # === 2) 兜底：bash 包装（仅 POSIX；Windows 主机会到不了这里，
        #     因为 PassthroughSandbox 已经走 native 了） ===
        task_id = _gen_task_id()
        log_path = f"{_BG_DIR}/{task_id}.log"
        exit_path = f"{_BG_DIR}/{task_id}.exit"

        env_prefix = ""
        if env_vars:
            env_prefix = " ".join(f"{shlex.quote(k)}={shlex.quote(v)}" for k, v in env_vars.items()) + " "

        cd_prefix = f"cd {shlex.quote(workdir)} && " if workdir else ""
        bg_dir = shlex.quote(_BG_DIR)
        log_q = shlex.quote(log_path)
        exit_q = shlex.quote(exit_path)
        cmd_q = shlex.quote(command)
        runner = (
            f"if command -v setsid >/dev/null 2>&1; then "
            f"setsid bash -c {cmd_q}; "
            f"else nohup bash -c {cmd_q}; fi"
        )
        wrapped = (
            f"mkdir -p {bg_dir} && "
            f"({cd_prefix}{env_prefix}({runner}) > {log_q} 2>&1; echo $? > {exit_q}) "
            f"</dev/null & echo $!"
        )
        rc, out, err = await self._shell(sandbox, wrapped, timeout=10)
        pid = None
        if rc == 0:
            try:
                pid = int((out or "").strip().splitlines()[-1])
            except Exception:
                pid = None
        task_info = {
            "task_id": task_id,
            "pid": pid,
            "log_path": log_path,
            "exit_path": exit_path,
            "command": command,
            "started_at": time.time(),
            "mode": "shell",
        }
        ExecuteCommandTool._BG_TASKS[task_id] = task_info
        return task_info

    async def _read_tail(self, sandbox: Any, task_info: Dict[str, Any], max_bytes: int = 8192) -> str:
        if task_info.get("mode") == "native":
            try:
                return await sandbox.read_background_output(task_info["task_id"], max_bytes=max_bytes)
            except Exception as exc:
                logger.warning(f"read_background_output 失败: {exc}")
                return ""
        path = task_info.get("log_path")
        if not path:
            return ""
        rc, out, _ = await self._shell(
            sandbox, f"tail -c {max_bytes} {shlex.quote(path)} 2>/dev/null || true", timeout=5
        )
        return out

    async def _is_alive(self, sandbox: Any, task_info: Dict[str, Any]) -> bool:
        if task_info.get("mode") == "native":
            try:
                return await sandbox.is_background_alive(task_info["task_id"])
            except Exception:
                return False
        pid = task_info.get("pid")
        if not pid:
            return False
        rc, _, _ = await self._shell(sandbox, f"kill -0 {pid} 2>/dev/null", timeout=3)
        return rc == 0

    async def _read_exit(self, sandbox: Any, task_info: Dict[str, Any]) -> Optional[int]:
        if task_info.get("mode") == "native":
            try:
                return await sandbox.get_background_exit_code(task_info["task_id"])
            except Exception:
                return None
        exit_path = task_info.get("exit_path")
        if not exit_path:
            return None
        rc, out, _ = await self._shell(sandbox, f"cat {shlex.quote(exit_path)} 2>/dev/null || true", timeout=3)
        text = (out or "").strip()
        if not text:
            return None
        try:
            return int(text.splitlines()[-1])
        except Exception:
            return None

    async def _wait_for_finish(
        self,
        sandbox: Any,
        task_info: Dict[str, Any],
        block_until_ms: int,
        pattern: Optional[str] = None,
    ) -> Tuple[bool, Optional[int]]:
        """轮询直到命令结束 / 超时 / 命中 pattern。返回 (finished, exit_code)。"""
        deadline = time.time() + max(0, block_until_ms) / 1000.0
        compiled = None
        if pattern:
            try:
                compiled = re.compile(pattern)
            except Exception as exc:
                logger.warning(f"await_shell pattern 编译失败，忽略: {exc}")
                compiled = None

        sleep_s = 0.2
        while True:
            exit_code = await self._read_exit(sandbox, task_info)
            if exit_code is not None:
                return True, exit_code

            if compiled is not None:
                tail = await self._read_tail(sandbox, task_info, max_bytes=16384)
                if tail and compiled.search(tail):
                    return False, None

            if time.time() >= deadline:
                return False, None
            await asyncio.sleep(sleep_s)
            sleep_s = min(1.0, sleep_s * 1.5)

    @tool(
        description_i18n={
            "zh": (
                "在沙箱中执行 Shell 命令；支持两段式执行。"
                "block_until_ms=0 立即放后台并返回 task_id；>0 阻塞至命令结束或到点。"
                "若到点未结束，返回 task_id + tail_output，可用 await_shell 继续等待，或用 kill_shell 终止。"
            ),
            "en": (
                "Execute a shell command in sandbox with two-stage support. "
                "block_until_ms=0 backgrounds the command and returns immediately with a task_id. "
                ">0 blocks until completion or deadline. On deadline, returns task_id + tail_output; "
                "use await_shell to keep waiting or kill_shell to terminate."
            ),
        },
        param_description_i18n={
            "command": {"zh": "待执行的 Shell 命令", "en": "Shell command to execute"},
            "workdir": {"zh": "执行目录（虚拟路径），默认沙箱工作区", "en": "Working directory (virtual path)"},
            "block_until_ms": {
                "zh": "阻塞等待毫秒数；0 表示立即后台运行；默认 30000",
                "en": "Block this many ms; 0 means background immediately; default 30000",
            },
            "env_vars": {"zh": "附加环境变量字典或 JSON 字符串", "en": "Additional env vars dict or JSON string"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "command": {"type": "string", "description": "Shell command to execute"},
            "workdir": {"type": "string", "description": "Working directory (virtual path)"},
            "block_until_ms": {"type": "integer", "default": 30000},
            "env_vars": {"type": "string", "description": "Additional env vars as JSON object string"},
            "session_id": {"type": "string", "description": "Session ID"},
        },
        return_data={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "status": {"type": "string", "description": "completed | running | error"},
                "task_id": {"type": "string"},
                "output_file": {"type": "string"},
                "stdout": {"type": "string"},
                "exit_code": {"type": "integer"},
            },
            "required": ["success"]
        }
    )
    async def execute_shell_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        block_until_ms: int = 30000,
        env_vars: Optional[str] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("ExecuteCommandTool: session_id is required")

        parsed_env_vars = self._parse_env_vars(env_vars)
        logger.info(f"🖥️ ExecuteCommandTool: {command[:100]}{'...' if len(command) > 100 else ''} block_until_ms={block_until_ms}")

        # 安全检查
        is_safe, reason = self.security_manager.is_command_safe(command)
        if not is_safe:
            logger.warning(f"安全检查失败: {reason}")
            return make_tool_error(
                ToolErrorCode.SAFETY_BLOCKED,
                f"安全检查失败: {reason}",
                hint="请改用更安全的命令；如确需高危操作，请改由用户在终端手动执行。",
                command=command,
            )

        sandbox = self._get_sandbox(session_id)

        # 始终经由后台模式启动；阻塞模式下我们再轮询等待
        echo_header(command)
        try:
            task_info = await self._spawn_background(
                sandbox, command, workdir, parsed_env_vars
            )
        except Exception as exc:
            echo_footer(None)
            logger.error(f"ExecuteCommandTool: 启动后台命令失败: {exc}")
            return make_tool_error(
                ToolErrorCode.SANDBOX_ERROR,
                f"启动命令失败: {exc}",
                command=command,
            )

        pid = task_info.get("pid")
        log_path = task_info.get("log_path")
        if pid is None:
            echo_footer(None)
            return make_tool_error(
                ToolErrorCode.SANDBOX_ERROR,
                "无法获取后台命令的 PID",
                command=command,
            )

        task_id = task_info["task_id"]
        task_info["session_id"] = session_id

        try:
            if block_until_ms <= 0:
                tail = await self._read_tail(sandbox, task_info, max_bytes=2048)
                return {
                    "success": True,
                    "status": "running",
                    "task_id": task_id,
                    "pid": pid,
                    "output_file": log_path,
                    "tail_output": tail,
                    "command": command,
                    "message": f"已在后台启动，task_id={task_id}",
                }

            finished, exit_code = await self._wait_for_finish(sandbox, task_info, block_until_ms)
            tail = await self._read_tail(sandbox, task_info, max_bytes=8192)
            if finished:
                await self._cleanup_task(sandbox, task_id)
                return {
                    "success": exit_code == 0,
                    "status": "completed",
                    "task_id": task_id,
                    "pid": pid,
                    "exit_code": exit_code,
                    "stdout": tail,
                    "output_file": log_path,
                    "command": command,
                }
            return {
                "success": True,
                "status": "running",
                "task_id": task_id,
                "pid": pid,
                "output_file": log_path,
                "tail_output": tail,
                "command": command,
                "message": f"达到 block_until_ms={block_until_ms}，命令仍在运行；可用 await_shell 继续等待",
            }
        finally:
            echo_footer(None)

    async def _cleanup_task(self, sandbox: Any, task_id: str) -> None:
        info = self._BG_TASKS.pop(task_id, None)
        if not info:
            return
        if info.get("mode") == "native":
            try:
                await sandbox.cleanup_background(task_id)
            except Exception:
                pass

    @tool(
        description_i18n={
            "zh": "拉取后台 shell 任务的增量输出；可选 pattern 命中即返回。结束时返回 exit_code 并清理注册表。",
            "en": "Poll a background shell task for incremental output. Optional pattern returns early on match. On finish returns exit_code and cleans up.",
        },
        param_description_i18n={
            "task_id": {"zh": "execute_shell_command 返回的 task_id", "en": "task_id returned by execute_shell_command"},
            "block_until_ms": {"zh": "最多等待毫秒数，默认 10000", "en": "Max wait in ms, default 10000"},
            "pattern": {"zh": "可选正则；命中时立即返回", "en": "Optional regex; return early when matched"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "task_id": {"type": "string"},
            "block_until_ms": {"type": "integer", "default": 10000},
            "pattern": {"type": "string"},
            "session_id": {"type": "string"},
        },
    )
    async def await_shell(
        self,
        task_id: str,
        block_until_ms: int = 10000,
        pattern: Optional[str] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("ExecuteCommandTool: session_id is required")
        task_info = self._BG_TASKS.get(task_id)
        if not task_info:
            return make_tool_error(
                ToolErrorCode.NOT_FOUND,
                f"未找到 task_id={task_id} 对应的后台任务",
                task_id=task_id,
            )

        sandbox = self._get_sandbox(session_id)
        finished, exit_code = await self._wait_for_finish(sandbox, task_info, block_until_ms, pattern=pattern)
        tail = await self._read_tail(sandbox, task_info, max_bytes=8192)
        if finished:
            await self._cleanup_task(sandbox, task_id)
            return {
                "success": exit_code == 0,
                "status": "completed",
                "task_id": task_id,
                "exit_code": exit_code,
                "stdout": tail,
                "output_file": task_info.get("log_path"),
            }
        return {
            "success": True,
            "status": "running",
            "task_id": task_id,
            "tail_output": tail,
            "output_file": task_info.get("log_path"),
            "matched_pattern": bool(pattern),
        }

    @tool(
        description_i18n={
            "zh": "终止后台 shell 任务：先发 SIGTERM，2 秒后仍存活则升级 SIGKILL。",
            "en": "Terminate a background shell task: SIGTERM first, escalate to SIGKILL if still alive after 2s.",
        },
        param_description_i18n={
            "task_id": {"zh": "execute_shell_command 返回的 task_id", "en": "task_id returned by execute_shell_command"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "task_id": {"type": "string"},
            "session_id": {"type": "string"},
        },
    )
    async def kill_shell(
        self,
        task_id: str,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("ExecuteCommandTool: session_id is required")
        task_info = self._BG_TASKS.get(task_id)
        if not task_info:
            return make_tool_error(
                ToolErrorCode.NOT_FOUND,
                f"未找到 task_id={task_id} 对应的后台任务",
                task_id=task_id,
            )

        sandbox = self._get_sandbox(session_id)
        pid = task_info.get("pid")

        if task_info.get("mode") == "native":
            # 优先调用沙箱原生 kill，跨平台
            try:
                await sandbox.kill_background(task_id, force=False)
            except Exception as exc:
                logger.warning(f"kill_background SIGTERM 失败: {exc}")
            await asyncio.sleep(2.0)
            try:
                if await sandbox.is_background_alive(task_id):
                    await sandbox.kill_background(task_id, force=True)
            except Exception:
                pass
        else:
            if not pid:
                await self._cleanup_task(sandbox, task_id)
                return {"success": True, "status": "missing_pid", "task_id": task_id}
            await self._shell(sandbox, f"kill -- -{pid} 2>/dev/null; kill {pid} 2>/dev/null", timeout=5)
            await asyncio.sleep(2.0)
            if await self._is_alive(sandbox, task_info):
                await self._shell(sandbox, f"kill -9 -- -{pid} 2>/dev/null; kill -9 {pid} 2>/dev/null", timeout=5)

        tail = await self._read_tail(sandbox, task_info, max_bytes=2048)
        await self._cleanup_task(sandbox, task_id)
        return {
            "success": True,
            "status": "killed",
            "task_id": task_id,
            "pid": pid,
            "tail_output": tail,
        }
