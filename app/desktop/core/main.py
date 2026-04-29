"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""
import os
import sys

# 设置浏览器 headed 模式环境变量（必须在导入其他模块之前设置）
os.environ["AGENT_BROWSER_HEADED"] = "1"

# 1. Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))

if getattr(sys, 'frozen', False):
    if hasattr(sys, '_MEIPASS'):
        current_dir = sys._MEIPASS
    project_root = current_dir
else:
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))

sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "app"))

# Ensure sagents.prompts is imported so PyInstaller can find all prompt modules
try:
    import sagents.prompts
except ImportError:
    pass

import sys
from pathlib import Path

from dotenv import load_dotenv

# 指定加载的 .env 文件（保持不动）
load_dotenv(".env")


from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from common.core.config import init_startup_config
from common.core.context import get_request_id
from common.core.exceptions import register_exception_handlers
from common.core.middleware import register_cors_middleware, register_request_logging_middleware
from common.utils.logging import init_logging_base
from mcp_servers.anytool.anytool_http import AnyToolStreamableHTTPApp
from .user_context import get_desktop_user_claims
from .lifecycle import (
    cleanup_system,
    initialize_system,
    post_initialize_task,
)
from .routers import register_routes as register_chat_routes


def _safe_console_write(message: str, *, flush: bool = False) -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.write(message)
            if flush and hasattr(stream, "flush"):
                stream.flush()
            return
        except (BrokenPipeError, OSError, ValueError):
            continue
        except Exception:
            continue


def _safe_print(*args, sep: str = " ", end: str = "\n", flush: bool = False) -> None:
    message = sep.join(str(arg) for arg in args) + end
    _safe_console_write(message, flush=flush)


@asynccontextmanager
async def app_lifespan(app: FastAPI):

    # 1) 核心系统初始化（必须先完成）
    await initialize_system()

    # 2) 异步后置初始化任务（可选）
    post_init_task = post_initialize_task()
    try:
        # 3) 启动 HTTP 服务
        yield
    finally:
        # 5) 等待后置任务完成（避免 shutdown 竞态）
        await post_init_task

        # 7) 清理系统资源
        await cleanup_system()


def create_fastapi_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""

    # 创建 FastAPI 应用
    app = FastAPI(
        title="Sage Desktop",
        description="基于 Sage 框架的智能体桌面端服务",
        version="1.0.0",
        lifespan=app_lifespan,
    )

    # 注册中间件
    register_cors_middleware(app)
    register_request_logging_middleware(app)

    @app.middleware("http")
    async def inject_desktop_user_context(request, call_next):
        internal_user_id = str(request.headers.get("X-Sage-Internal-UserId") or "").strip()
        if internal_user_id:
            request.state.user_claims = {
                "userid": internal_user_id,
                "username": internal_user_id,
                "nickname": internal_user_id,
                "role": "user",
            }
        else:
            request.state.user_claims = get_desktop_user_claims()
        return await call_next(request)

    # 注册异常处理器
    register_exception_handlers(app)

    # 注册 HTTP API 路由
    register_chat_routes(app)
    app.mount("/api/mcp/anytool", AnyToolStreamableHTTPApp())

    @app.get("/active")
    def active():
        return "Service is available."

    return app


def start_server(port: int = 8000):
    """
    启动 Uvicorn Server

    """
    un_cfg = uvicorn.Config(
        app=create_fastapi_app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        reload=False,
        factory=True,
        timeout_keep_alive=65, # Keep-alive timeout slightly longer than heartbeat interval (20s)
    )
    server = uvicorn.Server(config=un_cfg)
    server.run()


def check_single_instance():
    """Check if another instance is already running using PID file."""
    if sys.platform == "win32":
        # Tauri already enforces single-instance behavior on Windows.
        # Skip the POSIX-only PID file locking path that depends on fcntl.
        return True

    import atexit
    import fcntl
    import signal
    
    pid_file = Path("/tmp/sage_desktop.pid")
    
    try:
        # Try to open PID file
        fd = os.open(str(pid_file), os.O_RDWR | os.O_CREAT)
        
        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            # Lock failed, check if the process is actually running
            try:
                # Read the PID from file
                os.lseek(fd, 0, os.SEEK_SET)
                pid_data = os.read(fd, 1024).decode().strip()
                if pid_data:
                    old_pid = int(pid_data)
                    # Check if process exists
                    try:
                        os.kill(old_pid, 0)
                        # Process exists, kill it
                        _safe_print(
                            f"Warning: Another Sage Desktop instance is running (PID: {old_pid}), terminating it...",
                            flush=True,
                        )
                        try:
                            # Try graceful termination first
                            os.kill(old_pid, signal.SIGTERM)
                            # Wait a bit for the process to terminate
                            import time
                            time.sleep(2)
                            # Check if it's still running
                            try:
                                os.kill(old_pid, 0)
                                # Still running, force kill
                                _safe_print(f"Force killing process {old_pid}...", flush=True)
                                os.kill(old_pid, signal.SIGKILL)
                                time.sleep(1)
                            except (OSError, ProcessLookupError):
                                # Process terminated successfully
                                pass
                            _safe_print(f"Old process {old_pid} terminated.", flush=True)
                        except (OSError, ProcessLookupError) as e:
                            _safe_print(f"Failed to terminate old process: {e}", flush=True)
                        
                        # Clean up old PID file and retry
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
                        pid_file.unlink(missing_ok=True)
                        return check_single_instance()
                    except (OSError, ProcessLookupError):
                        # Process doesn't exist, stale PID file
                        _safe_print(
                            f"Warning: Stale PID file found (PID {old_pid} not running), removing...",
                            flush=True,
                        )
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
                        pid_file.unlink(missing_ok=True)
                        # Retry
                        return check_single_instance()
                else:
                    # Empty PID file, remove it
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    pid_file.unlink(missing_ok=True)
                    return check_single_instance()
            except (ValueError, OSError) as e:
                # Invalid PID or other error, remove stale file
                _safe_print(f"Warning: Invalid PID file, removing: {e}", flush=True)
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                except:
                    pass
                pid_file.unlink(missing_ok=True)
                return check_single_instance()
        
        # Write current PID
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        
        # Register cleanup on exit
        def cleanup():
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                pid_file.unlink(missing_ok=True)
            except:
                pass
        
        atexit.register(cleanup)
        return True
        
    except Exception as e:
        _safe_print(f"Warning: Could not create PID file lock: {e}", flush=True)
        return True


def main():
    try:
        # Check single instance before anything else
        check_single_instance()
        
        # Force stdout to be unbuffered when the underlying stream supports it.
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(line_buffering=True, write_through=True)
        except (OSError, ValueError):
            pass
        
        # Windows specific event loop policy
        if sys.platform == 'win32':
            import asyncio
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except AttributeError:
                pass

        user_home = Path.home()
        sage_home = user_home / ".sage"
        sage_home.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("SAGE_SHARED_PYTHON_ENV", "1")
        os.environ.setdefault("SAGE_SHARED_PYTHON_ENV_DIR", str(sage_home / ".sage_py_env"))

        logs_dir = sage_home / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        skills_dir = sage_home / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        
        # Sync IDE skills to Sage skills folder
        # Disabled temporarily: do not auto-import external IDE/CLI skills on desktop startup.
        # try:
        #     from .skill_sync import sync_skills_with_logging
        #     sync_skills_with_logging()
        # except Exception as e:
        #     print(f"Warning: Failed to sync IDE skills: {e}", flush=True)
        
        agents_workspace_dir = sage_home / "agents"
        agents_workspace_dir.mkdir(parents=True, exist_ok=True)

        sessions_dir = sage_home / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        os.environ["SAGE_SESSIONS_PATH"] = str(sessions_dir)

        cfg = init_startup_config(mode="desktop")
        # Ensures CORSMiddleware uses desktop allowlist even if cfg.app_mode were mis-set.
        os.environ["SAGE_INTERNAL_DESKTOP_PROCESS"] = "1"

        # Get port from environment variable SAGE_PORT, or find a free one if not set
        port_env = os.environ.get("SAGE_PORT")
        if port_env:
            try:
                port = int(port_env)
                _safe_print(f"Using port from environment SAGE_PORT: {port}", flush=True)
            except ValueError:
                _safe_print(
                    f"Invalid SAGE_PORT environment variable: {port_env}, finding free port...",
                    flush=True,
                )
                port = None
        else:
            port = None

        if port is None:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                s.listen(1)
                port = s.getsockname()[1]
            os.environ["SAGE_PORT"] = str(port)
            _safe_print(f"Set SAGE_PORT environment variable to {port}", flush=True)
            
        _safe_print(f"Starting Sage Desktop Server on port {port}...", flush=True)
        init_logging_base(
            log_name="sage-desktop",
            log_level="INFO",
            log_path=str(logs_dir),
            get_request_id=get_request_id,
            use_safe_stdout=True,
        )
        start_server(port)
        return 0
    except KeyboardInterrupt:
        print("服务收到中断信号，正在退出...", flush=True)
        return 0
    except SystemExit:
        return 0
    except Exception:
        import traceback

        _safe_print(traceback.format_exc(), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
