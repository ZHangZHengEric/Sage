import os
import asyncio
import subprocess
import threading
from pathlib import Path

from loguru import logger

from .bootstrap import (
    close_observability,
    close_skill_manager,
    close_tool_manager,
    copy_wiki_docs,
    initialize_observability,
    initialize_db_connection,
    initialize_im_service,
    initialize_skill_manager,
    initialize_tool_manager,
    initialize_session_manager,
    shutdown_clients,
    validate_and_disable_mcp_servers,
)
from common.utils.async_utils import create_safe_task
from .services.chat.stream_manager import StreamManager
from .services.browser_capability import get_browser_capability_coordinator

_memory_reporter_task = None
_host_watchdog_task = None
_browser_capability_coordinator = None


def _setup_memory_root_path():
    """设置 MEMORY_ROOT_PATH 环境变量为 ~/.sage/memory"""
    user_home = Path.home()
    sage_home = user_home / ".sage"
    memory_path = sage_home / "memory"
    memory_path.mkdir(parents=True, exist_ok=True)
    os.environ["MEMORY_ROOT_PATH"] = str(memory_path)
    logger.info(f"MEMORY_ROOT_PATH 已设置为: {memory_path}")


async def initialize_system():
    logger.info("sage-desktop：开始初始化")
    _setup_memory_root_path()
    _start_host_watchdog()
    await initialize_observability()
    await initialize_db_connection()
    await initialize_tool_manager()
    global _browser_capability_coordinator
    _browser_capability_coordinator = get_browser_capability_coordinator()
    _browser_capability_coordinator.start()
    await initialize_skill_manager()
    await copy_wiki_docs()  # 复制 wiki 文档到用户目录
    await initialize_session_manager()
    await initialize_im_service()
    StreamManager.get_instance()
    logger.info("sage-desktop：StreamManager 已预初始化")
    logger.info("sage-desktop：初始化完成")
    _start_memory_reporter()


def post_initialize_task():
    """
    服务启动完成后执行一次的后置任务
    """
    logger.info("sage-desktop：启动的后置任务...")
    return create_safe_task(_post_initialize(), name="post_initialize")


async def _post_initialize():
    await validate_and_disable_mcp_servers()
    create_safe_task(_ensure_default_anytool_server_ready(), name="ensure_default_anytool_server")
    await _start_task_scheduler()


async def _ensure_default_anytool_server_ready():
    """启动时异步注册默认 AnyTool MCP server。

    必须保证：无论如何不阻塞 lifecycle / 主事件循环。
    在 Windows 上观察到 streamable_http(127.0.0.1) 偶尔会因 TCP 握手 / 自身 HTTP 路由
    尚未挂载而 hang 住。因此每次注册都加 ``asyncio.wait_for`` 超时兜底，
    超时后直接进入下一次重试，最差结果是该 MCP server 暂未激活，不影响其它能力。
    """
    from common.services.mcp_service import ensure_default_anytool_server

    per_attempt_timeout = float(os.environ.get("SAGE_DEFAULT_ANYTOOL_TIMEOUT", "20"))

    for attempt in range(3):
        try:
            await asyncio.sleep(2 if attempt == 0 else 3)
            await asyncio.wait_for(
                ensure_default_anytool_server(register_tool_manager=True),
                timeout=per_attempt_timeout,
            )
            logger.info("sage-desktop：默认 AnyTool MCP server 已激活")
            return
        except asyncio.TimeoutError:
            logger.warning(
                f"sage-desktop：默认 AnyTool MCP server 激活第 {attempt + 1} 次超时"
                f"（{per_attempt_timeout}s），稍后重试"
            )
        except Exception as exc:
            logger.warning(f"sage-desktop：默认 AnyTool MCP server 激活失败（第 {attempt + 1} 次）: {exc}")


async def _start_task_scheduler():
    try:
        await asyncio.sleep(5)
        from mcp_servers.task_scheduler.task_scheduler_server import ensure_scheduler_started

        started = ensure_scheduler_started()
        logger.info(f"sage-desktop：TaskScheduler {'已启动' if started else '已存在'}")
    except Exception as exc:
        logger.warning(f"sage-desktop：TaskScheduler 启动失败: {exc}")


def _host_process_is_alive(host_pid: int) -> bool:
    if host_pid <= 0 or host_pid == os.getpid():
        return True

    if os.name == "nt":
        # Windows 上 os.kill(pid, 0) 会把进程当成 CTRL+BREAK 目标，会误杀。
        # 改用 OpenProcess(SYNCHRONIZE) + WaitForSingleObject 的轻量探测。
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259  # 进程还活着时 GetExitCodeProcess 返回的占位码

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, host_pid)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True  # 拿不到退出码，保守认为活着
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True

    try:
        os.kill(host_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


async def _host_watchdog_loop(host_pid: int):
    logger.info(f"[SageHostWatchdog] watching host pid={host_pid}")
    while True:
        try:
            await asyncio.sleep(15)
            if _host_process_is_alive(host_pid):
                continue

            logger.warning(
                f"[SageHostWatchdog] host pid={host_pid} is gone; exiting orphaned desktop backend pid={os.getpid()}"
            )
            os._exit(0)
        except asyncio.CancelledError:
            logger.info("[SageHostWatchdog] stopped")
            raise
        except Exception as exc:
            logger.warning(f"[SageHostWatchdog] error: {exc}")


def _start_host_watchdog():
    global _host_watchdog_task

    if _host_watchdog_task and not _host_watchdog_task.done():
        return

    raw_host_pid = str(os.environ.get("SAGE_HOST_PID") or "").strip()
    if not raw_host_pid:
        return

    try:
        host_pid = int(raw_host_pid)
    except ValueError:
        logger.warning(f"[SageHostWatchdog] invalid SAGE_HOST_PID={raw_host_pid!r}")
        return

    if host_pid <= 0 or host_pid == os.getpid():
        return

    _host_watchdog_task = create_safe_task(
        _host_watchdog_loop(host_pid),
        name="sidecar_host_watchdog",
    )


def _get_process_rss_mb() -> float | None:
    """跨平台获取当前进程 RSS（MB）。

    - POSIX：用 ``ps -o rss=``。
    - Windows：``ps`` 不存在，改用 ``ctypes`` 调 ``GetProcessMemoryInfo``，失败再静默返回 None。
    任何异常都吞掉，仅作监控用，不能影响 lifecycle。
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if not ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return None
            return round(counters.WorkingSetSize / (1024 * 1024), 1)
        except Exception:
            return None

    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return None
        rss_kb = int(result.stdout.strip() or "0")
        return round(rss_kb / 1024, 1)
    except Exception:
        return None


async def _memory_reporter_loop():
    from mcp_servers.im_server.service_manager import get_service_manager

    while True:
        try:
            await asyncio.sleep(600)
            rss_mb = _get_process_rss_mb()
            thread_count = threading.active_count()
            task_count = len(asyncio.all_tasks())

            service_manager = get_service_manager()
            channels = service_manager.list_all_channels()
            connected = sum(1 for item in channels if item.get("status") == "connected")
            errored = sum(1 for item in channels if item.get("status") == "error")

            logger.info(
                "[SageMemory][sidecar] rss_mb={} threads={} asyncio_tasks={} im_channels={} im_connected={} im_error={}",
                rss_mb,
                thread_count,
                task_count,
                len(channels),
                connected,
                errored,
            )
        except asyncio.CancelledError:
            logger.info("[SageMemory][sidecar] reporter stopped")
            raise
        except Exception as exc:
            logger.warning(f"[SageMemory][sidecar] reporter error: {exc}")


def _start_memory_reporter():
    global _memory_reporter_task
    if _memory_reporter_task and not _memory_reporter_task.done():
        return
    _memory_reporter_task = create_safe_task(_memory_reporter_loop(), name="sidecar_memory_reporter")


async def cleanup_system():
    logger.info("sage-desktop：正在清理资源...")
    global _memory_reporter_task, _host_watchdog_task, _browser_capability_coordinator
    if _host_watchdog_task:
        _host_watchdog_task.cancel()
        try:
            await _host_watchdog_task
        except asyncio.CancelledError:
            pass
        _host_watchdog_task = None
    if _memory_reporter_task:
        _memory_reporter_task.cancel()
        try:
            await _memory_reporter_task
        except asyncio.CancelledError:
            pass
        _memory_reporter_task = None
    if _browser_capability_coordinator:
        await _browser_capability_coordinator.stop()
        _browser_capability_coordinator = None
    await close_observability()
    # 关闭第三方客户端
    await shutdown_clients()
    try:
        await close_skill_manager()
    finally:
        logger.info("sage-desktop：技能管理器 已关闭")
    try:
        await close_tool_manager()
    finally:
        logger.info("sage-desktop：工具管理器 已关闭")
