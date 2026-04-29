"""跨平台主机后台进程运行器。

PassthroughSandboxProvider 与 LocalSandboxProvider 共用此实现，
使用纯 Python ``subprocess.Popen`` 启动后台进程：
- POSIX（Linux/macOS）：``start_new_session=True``，子进程成为新 session leader，
  便于按 pgid 整组杀。
- Windows：``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW``，
  子进程脱离父控制台并形成自己的进程组。

输出统一重定向到 ``<log_dir>/<task_id>.log``（合并 stdout / stderr），
exit code 通过 ``Popen.poll()`` 获取，避免 shell 拼接 ``echo $? > file`` 这种
跨平台陷阱。
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from typing import Any, Dict, Optional

from sagents.utils.logger import logger


_IS_WINDOWS = os.name == "nt"


def _gen_task_id() -> str:
    return "shtask_" + uuid.uuid4().hex[:12]


class HostBackgroundRunner:
    """主机后台进程注册表 + 启动器，跨平台。

    多个 Sandbox 实例通常共享同一个进程，可以各自持有独立的 runner，
    或共用一个；这里不做强约束，由调用方决定。
    """

    def __init__(self, log_dir: Optional[str] = None):
        self._log_dir = log_dir or os.path.join(os.path.expanduser("~"), ".sage", "bg")
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except Exception as exc:
            logger.warning(f"HostBackgroundRunner: 创建日志目录失败 {self._log_dir}: {exc}")
        self._tasks: Dict[str, Dict[str, Any]] = {}

    @property
    def log_dir(self) -> str:
        return self._log_dir

    def start(
        self,
        command: str,
        workdir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        task_id = _gen_task_id()
        log_path = os.path.join(self._log_dir, f"{task_id}.log")
        log_fh = open(log_path, "wb")

        env = os.environ.copy()
        if env_vars:
            env.update({str(k): str(v) for k, v in env_vars.items()})

        cwd = workdir or None
        if cwd and not os.path.isdir(cwd):
            # 目录不存在直接拒绝，避免 Popen 抛出 FileNotFoundError 拿不到 task
            try:
                log_fh.close()
            except Exception:
                pass
            raise FileNotFoundError(f"workdir 不存在: {cwd}")

        try:
            if _IS_WINDOWS:
                creationflags = 0
                # DETACHED_PROCESS = 0x8, CREATE_NEW_PROCESS_GROUP = 0x200
                creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                    close_fds=False,
                )
            else:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except Exception:
            try:
                log_fh.close()
            except Exception:
                pass
            raise

        self._tasks[task_id] = {
            "task_id": task_id,
            "pid": proc.pid,
            "process": proc,
            "log_path": log_path,
            "log_fh": log_fh,
            "command": command,
            "started_at": time.time(),
        }
        logger.info(f"HostBackgroundRunner: 启动后台任务 task_id={task_id} pid={proc.pid}")
        return {"task_id": task_id, "pid": proc.pid, "log_path": log_path}

    def read_tail(self, task_id: str, max_bytes: int = 8192) -> str:
        info = self._tasks.get(task_id)
        if not info:
            return ""
        path = info["log_path"]
        try:
            with open(path, "rb") as f:
                try:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    truncated = size > max_bytes
                    if truncated:
                        f.seek(size - max_bytes)
                    else:
                        f.seek(0)
                    data = f.read()
                except Exception:
                    data = b""
                    truncated = False
            # 截断时丢掉可能不完整的首行碎片，避免半行污染
            if truncated:
                nl = data.find(b"\n")
                if 0 <= nl < min(len(data), 4096):
                    data = data[nl + 1:]
            return data.decode("utf-8", errors="replace")
        except FileNotFoundError:
            return ""
        except Exception as exc:
            logger.warning(f"HostBackgroundRunner: 读取日志失败 {path}: {exc}")
            return ""

    def get_log_size(self, task_id: str) -> Optional[int]:
        """返回日志文件总字节数；task 不存在或文件不存在返回 ``None``。"""
        info = self._tasks.get(task_id)
        if not info:
            return None
        path = info.get("log_path")
        if not path:
            return None
        try:
            return os.path.getsize(path)
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning(f"HostBackgroundRunner: 读取日志大小失败 {path}: {exc}")
            return None

    def is_alive(self, task_id: str) -> bool:
        info = self._tasks.get(task_id)
        if not info:
            return False
        return info["process"].poll() is None

    def get_exit_code(self, task_id: str) -> Optional[int]:
        info = self._tasks.get(task_id)
        if not info:
            return None
        rc = info["process"].poll()
        return rc

    def kill(self, task_id: str, force: bool = False) -> bool:
        info = self._tasks.get(task_id)
        if not info:
            return False
        proc = info["process"]
        if proc.poll() is not None:
            return True
        try:
            if _IS_WINDOWS:
                # CTRL_BREAK_EVENT 需要进程组，这里直接 terminate / kill
                if force:
                    proc.kill()
                else:
                    proc.terminate()
            else:
                import signal
                sig = signal.SIGKILL if force else signal.SIGTERM
                pgid = None
                try:
                    pgid = os.getpgid(proc.pid)
                except Exception:
                    pgid = None
                if pgid is not None:
                    try:
                        os.killpg(pgid, sig)
                    except ProcessLookupError:
                        pass
                    except Exception:
                        try:
                            proc.send_signal(sig)
                        except Exception:
                            pass
                else:
                    try:
                        proc.send_signal(sig)
                    except Exception:
                        pass
            return True
        except Exception as exc:
            logger.warning(f"HostBackgroundRunner: kill 失败 task_id={task_id}: {exc}")
            return False

    def cleanup(self, task_id: str) -> None:
        info = self._tasks.pop(task_id, None)
        if not info:
            return
        try:
            info["log_fh"].close()
        except Exception:
            pass

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)


__all__ = ["HostBackgroundRunner"]
