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
    await _start_task_scheduler()


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

    try:
        os.kill(host_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Treat permission errors as "still alive" to avoid false positives.
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
