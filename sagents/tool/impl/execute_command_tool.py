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

# completion event 的 tail 最大字节数。reminder 只是"知会"通知，agent 想看完整结果应调
# await_shell。保持小一些可以避免长会话里 reminder 累积失控。
_REMINDER_TAIL_MAX_BYTES = 512

# _BG_TASKS 的硬性最长存活时间。任何 task 自 ``started_at`` 起 12 小时未被消费会被
# 强制 GC（_BG_TASKS / _COMPLETION_EVENTS / sandbox cleanup）。每次 spawn 触发一次扫描。
_BG_TASK_MAX_AGE_S = 12 * 3600


_ERROR_KEYWORDS = re.compile(
    r'error|exception|traceback|fatal|fail|stderr|critical|abort|killed|oom',
    re.IGNORECASE,
)


def _truncate_tail_for_reminder(text: str, max_bytes: int = _REMINDER_TAIL_MAX_BYTES) -> str:
    """对 reminder 用 tail 做尾部优先的截断，尾部全空行时补一条错误行。

    逻辑：
    1. 从尾部取 max_bytes 字节，保留最后几行（drop 被截断的首行碎片）。
    2. 若截出来的内容去掉空白后为空（命令无输出），从原始文本中反向搜
       第一条包含 error/exception/traceback 等关键词的行追加到头部，
       帮助 agent 快速感知失败原因。
    3. 不超 max_bytes 时直接返回原文。
    """
    if not text:
        return ""
    raw = text.encode("utf-8", errors="ignore")
    if len(raw) <= max_bytes:
        return text

    truncated = raw[-max_bytes:]
    nl = truncated.find(b"\n")
    if 0 <= nl < max_bytes - 1:
        truncated = truncated[nl + 1:]
    tail_str = truncated.decode("utf-8", errors="ignore")
    result = "...<truncated>...\n" + tail_str

    # 若尾部有效内容为空，补一条错误行（反向搜索原始文本，取最后一条命中行）
    if not tail_str.strip():
        error_line = ""
        for line in reversed(text.splitlines()):
            if line.strip() and _ERROR_KEYWORDS.search(line):
                error_line = line.strip()
                break
        if error_line:
            result = f"[key line] {error_line}\n" + result

    return result

# _BG_TASKS 的硬性最长存活时间。任何 task 自 ``started_at`` 起 12 小时未被消费会被
# 强制 GC（_BG_TASKS / _COMPLETION_EVENTS / sandbox cleanup）。每次 spawn 触发一次扫描。
_BG_TASK_MAX_AGE_S = 12 * 3600


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


def _suggest_next_block_ms(running_ms: int) -> int:
    """根据已运行时长建议下一次 await_shell 的 block_until_ms。

    分档：
    - < 30s：建议 60000（1 分钟）
    - 30s–5min：建议 min(running_ms * 1.5, 300000)
    - > 5min：建议 600000（10 分钟）
    """
    if running_ms < 30_000:
        return 60_000
    if running_ms < 300_000:
        return min(int(running_ms * 1.5), 300_000)
    return 600_000


class ExecuteCommandTool:
    """命令执行工具 - 通过沙箱执行命令。两段式 + 后台进程注册表 + 完成事件队列。"""

    # 进程级注册表：task_id -> {session_id, pid, log_path, exit_path, command, started_at}
    _BG_TASKS: Dict[str, Dict[str, Any]] = {}

    # 完成事件字典：session_id -> {task_id: event_dict}
    # 事件结构：{task_id, command, exit_code, elapsed_ms, tail}
    # 写入：watcher 在命令完成时写入；
    # 消费路径：
    #   1) await_shell 返回 completed 时 consume_completion_event 显式消费；
    #   2) _call_llm_streaming 在每次 LLM 请求前 pop_completion_events 全部 flush 注入。
    # 两条路径互斥：被 await_shell 消费过的不会再走 LLM flush。
    _COMPLETION_EVENTS: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def __init__(self):
        self.security_manager = SecurityManager()

    @classmethod
    def pop_completion_events(cls, session_id: str) -> List[Dict[str, Any]]:
        """取出指定 session 下所有 pending completion 事件并清空。

        被 ``_call_llm_streaming`` 在每次 LLM 请求前调用；返回的事件会被注入为
        ``<system_reminder>`` 消息。
        """
        if not session_id:
            return []
        bucket = cls._COMPLETION_EVENTS.pop(session_id, None)
        if not bucket:
            return []
        return list(bucket.values())

    @classmethod
    def consume_completion_event(cls, session_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        """显式消费某 session 下指定 task_id 的事件（如果存在）。

        ``await_shell`` 显式拿到 completed 时调用，避免与 system_reminder 重复通知。
        """
        if not session_id or not task_id:
            return None
        bucket = cls._COMPLETION_EVENTS.get(session_id)
        if not bucket:
            return None
        ev = bucket.pop(task_id, None)
        if not bucket:
            cls._COMPLETION_EVENTS.pop(session_id, None)
        return ev

    @classmethod
    def _emit_completion_event(
        cls,
        session_id: str,
        task_id: str,
        command: str,
        exit_code: Optional[int],
        elapsed_ms: int,
        tail: str,
    ) -> None:
        if not session_id or not task_id:
            return
        cls._COMPLETION_EVENTS.setdefault(session_id, {})[task_id] = {
            "task_id": task_id,
            "command": command,
            "exit_code": exit_code,
            "elapsed_ms": elapsed_ms,
            "tail": tail,
        }

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

    async def _watch_completion(
        self,
        sandbox: Any,
        task_info: Dict[str, Any],
        session_id: str,
    ) -> None:
        """后台 watcher：轮询命令直到结束，写入 completion 事件。

        - 写入路径：``_COMPLETION_EVENTS[session_id][task_id]``
        - LLM 在下一次请求前 ``pop_completion_events`` 取出注入为 system_reminder
        - 若 ``await_shell`` 抢先拿到结果并 ``consume_completion_event``，事件会被显式删除，
          watcher 后写入会被覆盖也无所谓——下次 await_shell completed 时会再消费一次。
        - 真正去重的关键是：watcher 写入时若 task 已经被 ``_cleanup_task`` 清理（说明
          await_shell 路径已处理），就不再写事件。
        """
        task_id = task_info["task_id"]
        sleep_s = 0.5
        try:
            while True:
                await asyncio.sleep(sleep_s)
                sleep_s = min(2.0, sleep_s * 1.3)

                if task_id not in ExecuteCommandTool._BG_TASKS:
                    return

                exit_code = await self._read_exit(sandbox, task_info)
                if exit_code is not None:
                    break

            if task_id not in ExecuteCommandTool._BG_TASKS:
                return

            # 这里读取的 tail 仅用于 system_reminder 知会，agent 想看完整结果应调 await_shell；
            # 多读一些再截断，保留尾部关键信息。
            raw_tail = await self._read_tail(sandbox, task_info, max_bytes=4096)
            short_tail = _truncate_tail_for_reminder(raw_tail or "")
            elapsed_ms = int((time.time() - task_info.get("started_at", time.time())) * 1000)
            self._emit_completion_event(
                session_id=session_id,
                task_id=task_id,
                command=task_info.get("command", ""),
                exit_code=exit_code,
                elapsed_ms=elapsed_ms,
                tail=short_tail,
            )
            # 故意不调 _cleanup_task：
            # - sandbox-side exit/log 留给后续 await_shell 拿完整结果；
            # - _BG_TASKS 由 await_shell completed 路径清理；reminder 只做通知。
            # - 12h 仍未被消费的，由下次 spawn 触发的 _gc_stale_tasks 兜底强制清理。
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"_watch_completion 异常 task_id={task_id}: {exc}")

    async def _gc_stale_tasks(self) -> None:
        """清理 _BG_TASKS 与 _COMPLETION_EVENTS 中超过 12 小时的条目。

        每次 spawn 前调用；发现超期 task 时：
        1. 尝试 sandbox cleanup（忽略失败）；
        2. 从 _BG_TASKS 删除；
        3. 从对应 session 的 _COMPLETION_EVENTS 删除（若存在）。
        """
        now = time.time()
        stale = [
            tid for tid, info in list(self._BG_TASKS.items())
            if now - info.get("started_at", now) > _BG_TASK_MAX_AGE_S
        ]
        for tid in stale:
            info = self._BG_TASKS.pop(tid, None)
            if not info:
                continue
            sid = info.get("session_id", "")
            logger.info(f"GC: 清理超期 task_id={tid} session_id={sid}")
            try:
                sandbox = self._get_sandbox(sid) if sid else None
                if sandbox and info.get("mode") == "native":
                    await sandbox.cleanup_background(tid)
            except Exception as exc:
                logger.debug(f"GC: sandbox.cleanup_background({tid}) 失败（忽略）: {exc}")
            # 同步清理 _COMPLETION_EVENTS
            bucket = self.__class__._COMPLETION_EVENTS.get(sid)
            if bucket:
                bucket.pop(tid, None)
                if not bucket:
                    self.__class__._COMPLETION_EVENTS.pop(sid, None)

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
                "block_until_ms=0 立即放后台并返回 task_id；>0 阻塞至命令结束或到点（默认 30000）。"
                "若到点未结束，返回 task_id + tail_output；命令最终完成时系统会通过 "
                "<system_reminder> 主动通知，你不需要轮询，起完命令请优先去做下一步工作。"
                "若必须等待，可用 await_shell 并传入较大的 block_until_ms（>=60000），"
                "或用 kill_shell 终止。"
            ),
            "en": (
                "Execute a shell command in sandbox with two-stage support. "
                "block_until_ms=0 backgrounds the command and returns immediately with a task_id. "
                ">0 blocks until completion or deadline (default 30000). On deadline, returns task_id + tail_output. "
                "Eventual completion is pushed via <system_reminder>; you do NOT need to poll. "
                "After spawning, prefer to do the next step rather than waiting. "
                "If you must wait, use await_shell with a generous block_until_ms (>=60000), or kill_shell to terminate."
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

        # 每次 spawn 前顺手做一次 12h 超期 GC，不开独立定时器，避免复杂度
        try:
            await self._gc_stale_tasks()
        except Exception as _gc_exc:
            logger.debug(f"_gc_stale_tasks 异常（忽略）: {_gc_exc}")

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

        # 启动后台 watcher：命令结束时写入 completion 事件，供下一次 LLM 请求 flush 注入
        try:
            asyncio.create_task(self._watch_completion(sandbox, task_info, session_id))
        except RuntimeError:
            logger.warning("无法启动 completion watcher：当前无运行中的 event loop")

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
                # 同步拿到结果，显式消费 watcher 可能已写入的事件，避免重复通知
                self.consume_completion_event(session_id, task_id)
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
            running_ms = int((time.time() - task_info.get("started_at", time.time())) * 1000)
            return {
                "success": True,
                "status": "running",
                "task_id": task_id,
                "pid": pid,
                "output_file": log_path,
                "tail_output": tail,
                "running_for_ms": running_ms,
                "suggested_next_block_ms": _suggest_next_block_ms(running_ms),
                "command": command,
                "message": (
                    f"达到 block_until_ms={block_until_ms}，命令仍在运行。"
                    "完成时会通过 <system_reminder> 主动通知，无需轮询；"
                    "如必须等待，可用 await_shell 并传入较大 block_until_ms。"
                ),
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
            "zh": (
                "拉取后台 shell 任务的增量输出；可选 pattern 命中即返回；结束时返回 exit_code 并清理注册表。"
                "默认 block_until_ms=600000（10 分钟）。"
                "重要：仅在「下一步工作必须依赖此命令结果且当前没有别的事可做」时使用——"
                "后台命令完成会通过 <system_reminder> 主动通知，无需轮询。"
                "请按场景选择 block_until_ms："
                "短任务 60000–120000；已知会跑数分钟 120000–300000；训练/大型构建 600000–1200000。"
                "禁止以 < 30000 的间隔反复轮询；服务端会对小值做自适应改写。"
            ),
            "en": (
                "Poll a background shell task for incremental output. "
                "Optional pattern returns early on match. On finish returns exit_code and cleans up. "
                "Default block_until_ms=600000 (10 minutes). "
                "IMPORTANT: only use when the next step strictly depends on this command's result AND there is nothing else productive to do — "
                "completion will be pushed via <system_reminder>, polling is unnecessary. "
                "Pick block_until_ms by scenario: short tasks 60000–120000; multi-minute tasks 120000–300000; long builds/training 600000–1200000. "
                "Do not poll with < 30000ms intervals; the server will rewrite small values adaptively."
            ),
        },
        param_description_i18n={
            "task_id": {"zh": "execute_shell_command 返回的 task_id", "en": "task_id returned by execute_shell_command"},
            "block_until_ms": {
                "zh": "最多等待毫秒数；默认 600000（10 分钟）；建议按场景选择 60000+",
                "en": "Max wait in ms; default 600000 (10min); pick 60000+ by scenario",
            },
            "pattern": {"zh": "可选正则；命中时立即返回", "en": "Optional regex; return early when matched"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "task_id": {"type": "string"},
            "block_until_ms": {"type": "integer", "default": 600000},
            "pattern": {"type": "string"},
            "session_id": {"type": "string"},
        },
    )
    async def await_shell(
        self,
        task_id: str,
        block_until_ms: int = 600000,
        pattern: Optional[str] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("ExecuteCommandTool: session_id is required")
        # 顺带触发一次 GC，确保长期僵尸 task 被清理（spawn 不活跃的会话也能覆盖）
        try:
            await self._gc_stale_tasks()
        except Exception as _gc_exc:
            logger.debug(f"_gc_stale_tasks 异常（忽略）: {_gc_exc}")
        task_info = self._BG_TASKS.get(task_id)
        if not task_info:
            # task 已不在注册表，可能 watcher 已经写入完成事件并清理，
            # 也可能 await_shell / 另一个调用先消费过——尝试从事件队列中拿一次
            ev = self.consume_completion_event(session_id, task_id)
            if ev is not None:
                return {
                    "success": ev.get("exit_code") == 0,
                    "status": "completed",
                    "task_id": task_id,
                    "exit_code": ev.get("exit_code"),
                    "stdout": ev.get("tail", ""),
                }
            return make_tool_error(
                ToolErrorCode.NOT_FOUND,
                f"未找到 task_id={task_id} 对应的后台任务",
                task_id=task_id,
            )

        # 自适应改写：跑得越久，最低等待越长，避免反射性短间隔轮询
        running_ms = int((time.time() - task_info.get("started_at", time.time())) * 1000)
        requested_block_until_ms = block_until_ms
        if running_ms > 30_000 and block_until_ms < 60_000:
            block_until_ms = 60_000
        if running_ms > 300_000 and block_until_ms < 300_000:
            block_until_ms = 300_000

        sandbox = self._get_sandbox(session_id)
        finished, exit_code = await self._wait_for_finish(sandbox, task_info, block_until_ms, pattern=pattern)
        tail = await self._read_tail(sandbox, task_info, max_bytes=8192)
        if finished:
            self.consume_completion_event(session_id, task_id)
            await self._cleanup_task(sandbox, task_id)
            return {
                "success": exit_code == 0,
                "status": "completed",
                "task_id": task_id,
                "exit_code": exit_code,
                "stdout": tail,
                "output_file": task_info.get("log_path"),
            }
        running_ms_after = int((time.time() - task_info.get("started_at", time.time())) * 1000)
        return {
            "success": True,
            "status": "running",
            "task_id": task_id,
            "tail_output": tail,
            "output_file": task_info.get("log_path"),
            "matched_pattern": bool(pattern),
            "running_for_ms": running_ms_after,
            "suggested_next_block_ms": _suggest_next_block_ms(running_ms_after),
            "block_until_ms_requested": requested_block_until_ms,
            "block_until_ms_used": block_until_ms,
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
