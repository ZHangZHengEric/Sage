import json
import ast
import os
import platform
import sys
import hashlib
from contextlib import contextmanager
from typing import Any, Dict, List, Union, Optional


def get_system_python_path() -> Optional[str]:
    """返回当前 Server Runtime 使用的 Python 解释器。"""
    return sys.executable


def detect_machine_environment(
    sandbox: Optional[Any] = None,
    sandbox_agent_workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    收集轻量沙箱运行环境信息，供 agent 判断当前平台和执行边界。

    只读取 Python 与沙箱对象已有属性，不执行 shell 探测，避免拖慢 session 初始化。
    """
    environment = {
        "os": platform.system(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "path_separator": os.pathsep,
    }

    if sandbox is not None:
        environment.update(  # pyright: ignore[reportCallIssue]
            {  # pyright: ignore[reportArgumentType]
                "sandbox_type": sandbox.__class__.__name__,
                "sandbox_workspace": sandbox_agent_workspace
                or getattr(sandbox, "sandbox_agent_workspace", None),
                "sandbox_isolation": getattr(sandbox, "isolation_mode", None),
                "sandbox_python_venv": getattr(sandbox, "venv_dir", None),
                "sandbox_runtime_dir": getattr(sandbox, "sandbox_dir", None),
            }
        )

    return environment


def use_shared_python_env() -> bool:
    value = str(os.environ.get("SAGE_SHARED_PYTHON_ENV", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_shared_python_env_dir() -> str:
    custom_path = os.environ.get("SAGE_SHARED_PYTHON_ENV_DIR")
    if custom_path:
        return os.path.abspath(os.path.expanduser(custom_path))
    return os.path.join(os.path.expanduser("~"), ".sage", ".sage_py_env")


def get_shared_sandbox_runtime_root() -> str:
    custom_path = os.environ.get("SAGE_SHARED_SANDBOX_RUNTIME_DIR")
    if custom_path:
        return os.path.abspath(os.path.expanduser(custom_path))
    return os.path.join(os.path.expanduser("~"), ".sage", ".sandbox_runtime")


def resolve_python_venv_dir(workspace_path: Optional[str]) -> Optional[str]:
    if use_shared_python_env():
        return get_shared_python_env_dir()
    if not workspace_path:
        return None
    return os.path.join(workspace_path, ".sandbox", "venv")


def resolve_sandbox_runtime_dir(workspace_path: Optional[str]) -> Optional[str]:
    """
    统一解析本地沙箱运行时目录（launcher/input/output/pylibs 等）。

    优先级：
    1) SAGE_SANDBOX_RUNTIME_DIR（固定目录）
    2) 共享环境模式：~/.sage/.sandbox_runtime/<workspace-hash>
    3) 默认：<workspace>/.sandbox
    """
    forced_dir = os.environ.get("SAGE_SANDBOX_RUNTIME_DIR")
    if forced_dir:
        return os.path.abspath(os.path.expanduser(forced_dir))

    if not workspace_path:
        return None

    workspace_abs = os.path.abspath(os.path.expanduser(workspace_path))
    if use_shared_python_env():
        root = get_shared_sandbox_runtime_root()
        digest = hashlib.sha1(workspace_abs.encode("utf-8")).hexdigest()[:12]
        workspace_name = os.path.basename(workspace_abs.rstrip(os.sep)) or "workspace"
        return os.path.join(root, f"{workspace_name}_{digest}")

    return os.path.join(workspace_abs, ".sandbox")


@contextmanager
def file_lock(lock_path: str):
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock_file = open(lock_path, "w")
    try:
        if os.name != "nt":
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name != "nt":
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def ensure_list(content: Union[str, List[Any]], separator: str = None) -> List[Any]:  # pyright: ignore[reportArgumentType]
    """
    Try to parse the input content into a list.

    Supports:
    1. Direct List input.
    2. JSON string parsing.
    3. Python literal evaluation (for stringified lists).
    4. Comma-separated strings (if not a JSON/Literal list).
    5. Space-separated strings (fallback).

    Args:
        content: The input string or list.
        separator: Optional specific separator to use for string splitting.
                   If provided, it overrides the auto-detection logic for delimiters.

    Returns:
        A list containing the parsed items. Returns [content] if parsing fails but input was a string.
        Returns [] if content is None or empty string.
    """
    if content is None:
        return []

    if isinstance(content, list):
        return content

    if not isinstance(content, str):
        return [content]

    content = content.strip()
    if not content:
        return []

    # 1. Try JSON parsing
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # 2. Try ast.literal_eval (safe eval)
    try:
        if content.startswith("[") and content.endswith("]"):
            parsed = ast.literal_eval(content)
            if isinstance(parsed, list):
                return parsed
    except Exception:
        pass

    # 3. Handle Delimiters (Comma or Space)
    # If a specific separator is provided, use it.
    if separator:
        return [item.strip() for item in content.split(separator) if item.strip()]

    # Auto-detect: if comma exists, assume comma-separated
    if "," in content:
        return [item.strip() for item in content.split(",") if item.strip()]

    # Auto-detect: if space exists, assume space-separated
    if " " in content:
        return [item.strip() for item in content.split(" ") if item.strip()]

    # 4. Fallback: return as single item list
    return [content]
