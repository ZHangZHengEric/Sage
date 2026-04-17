"""
Shell 命令实时回显工具

把沙箱里跑的 shell 命令输出实时写到当前进程的 sys.stdout，不走 logger（避免每行
都被加上 [INFO] 前缀和换行）。受环境变量 SAGE_ECHO_SHELL_OUTPUT 控制：
- 默认开启（"1"/"true"/"yes"/"on"），或不设置时
- 设置为 "0"/"false"/"no"/"off" 关闭

注意：这是"诊断/可观测"层面的回显，不是消息流；正常的工具结果仍然通过返回值传回
agent，互不冲突。
"""
import os
import signal
import subprocess
import sys
import threading
import time
from typing import List, Optional, Sequence, Tuple


_DISABLED_VALUES = {"0", "false", "no", "off", ""}


def echo_enabled() -> bool:
    """是否启用实时 stdout 回显。默认开启；显式设为 0/false/no/off/空 才关闭。"""
    val = os.environ.get("SAGE_ECHO_SHELL_OUTPUT", "1").strip().lower()
    return val not in _DISABLED_VALUES


def _safe_write(text: str) -> None:
    if not text:
        return
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except Exception:
        pass


def echo_chunk(chunk: str) -> None:
    """转发 stdout 增量片段。空字符串/None 直接忽略。"""
    if not echo_enabled():
        return
    _safe_write(chunk)


def echo_header(command: str, *, tag: str = "$") -> None:
    """命令开始前打印一行分隔，便于多命令时区分边界。"""
    if not echo_enabled():
        return
    text = command if command else ""
    if len(text) > 500:
        text = text[:500] + " …"
    _safe_write(f"\n{tag} {text}\n")


def echo_footer(return_code: Optional[int]) -> None:
    """命令结束打一行尾巴，标注 rc。"""
    if not echo_enabled():
        return
    rc_text = "?" if return_code is None else str(return_code)
    _safe_write(f"↪ rc={rc_text}\n")


def run_with_streaming_stdout(
    cmd: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, str, str]:
    """同步执行 cmd，stdout 增量读取并通过 echo_chunk 实时转发；stderr 单独完整捕获。

    设计目标：保持与 ``subprocess.run(capture_output=True, timeout=...)`` 相同的
    返回/异常语义，但允许调用者在等待结束的同时看到 stdout 实时输出。

    Args:
        cmd: 命令及参数。
        cwd: 工作目录。
        env: 环境变量。
        timeout: 超时秒数；超时会 SIGKILL 子进程并 raise ``subprocess.TimeoutExpired``。

    Returns:
        (returncode, captured_stdout, captured_stderr)
    """
    # 关键：start_new_session=True，让子进程独占一个进程组，超时时可以
    # 一次性 killpg 整个进程组，避免子孙进程（如 sleep）持有 stdout pipe 的
    # fd 导致 drain 线程一直阻塞在 read 上。
    popen_kwargs = dict(
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(list(cmd), **popen_kwargs)

    stdout_buf: List[str] = []
    stderr_buf: List[str] = []

    def _drain_stdout() -> None:
        try:
            while True:
                chunk = proc.stdout.read(4096) if proc.stdout else b""
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                stdout_buf.append(text)
                echo_chunk(text)
        except Exception:
            pass

    def _drain_stderr() -> None:
        try:
            while True:
                chunk = proc.stderr.read(4096) if proc.stderr else b""
                if not chunk:
                    break
                stderr_buf.append(chunk.decode("utf-8", errors="replace"))
        except Exception:
            pass

    t_out = threading.Thread(target=_drain_stdout, daemon=True)
    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_out.start()
    t_err.start()

    def _hard_kill() -> None:
        """干掉整个进程组（POSIX）或退化为 proc.kill（Windows / 已退出）。"""
        if os.name == "posix":
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            proc.kill()
        except Exception:
            pass

    deadline = (time.monotonic() + timeout) if timeout else None
    timed_out = False
    try:
        if deadline is None:
            proc.wait()
        else:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _hard_kill()
                    proc.wait()
                    break
                try:
                    proc.wait(timeout=min(remaining, 0.5))
                    break
                except subprocess.TimeoutExpired:
                    continue
    finally:
        # killpg 之后 pipe 应已关闭，drain 线程会很快返回；留 1s 兜底
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

    if timed_out:
        raise subprocess.TimeoutExpired(
            cmd=list(cmd),
            timeout=timeout,
            output="".join(stdout_buf),
            stderr="".join(stderr_buf),
        )

    return proc.returncode, "".join(stdout_buf), "".join(stderr_buf)
