import json
import ast
import os
import sys
import shutil
from contextlib import contextmanager
from typing import Any, List, Union, Optional


def is_pyinstaller_frozen() -> bool:
    """
    检测当前是否在 PyInstaller 打包环境中运行。
    
    Returns:
        bool: 如果是 PyInstaller 打包环境返回 True，否则返回 False
    """
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_system_python_path() -> Optional[str]:
    """
    获取系统 Python 解释器路径。
    
    在 PyInstaller 打包环境中，sys.executable 指向打包后的二进制文件，
    而不是 Python 解释器。此函数会尝试找到真正的 Python 解释器。
    
    Returns:
        str: Python 解释器路径，如果找不到则返回 None
    """
    # 如果在打包环境中，需要找到真正的 Python
    if is_pyinstaller_frozen():
        # 尝试常见的 Python 路径
        possible_paths = []
        
        if sys.platform == 'win32':
            # Windows 常见路径
            user_profile = os.environ.get('USERPROFILE', '')
            possible_paths = [
                os.path.join(user_profile, r'miniconda3\envs\sage-desktop-env\python.exe'),
                os.path.join(user_profile, r'anaconda3\envs\sage-desktop-env\python.exe'),
                r'C:\ProgramData\miniconda3\envs\sage-desktop-env\python.exe',
                r'C:\ProgramData\anaconda3\envs\sage-desktop-env\python.exe',
                r'C:\Python311\python.exe',
                r'C:\Python310\python.exe',
                r'C:\Python39\python.exe',
            ]
            # 尝试 py launcher
            py_launcher = shutil.which('py')
            if py_launcher:
                possible_paths.insert(0, py_launcher)
        else:
            # macOS/Linux 常见路径
            home_dir = os.environ.get('HOME', '')
            possible_paths = [
                os.path.join(home_dir, '.conda/envs/sage-desktop-env/bin/python'),
                os.path.join(home_dir, 'opt/anaconda3/envs/sage-desktop-env/bin/python'),
                os.path.join(home_dir, 'anaconda3/envs/sage-desktop-env/bin/python'),
                os.path.join(home_dir, 'miniconda3/envs/sage-desktop-env/bin/python'),
                '/opt/anaconda3/envs/sage-desktop-env/bin/python',
                '/opt/miniconda3/envs/sage-desktop-env/bin/python',
                '/usr/local/bin/python3',
                '/usr/bin/python3',
                '/opt/homebrew/bin/python3',
            ]
        
        # 检查这些路径是否存在
        for path in possible_paths:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        
        # 尝试使用 which 查找
        for cmd in ['python3', 'python']:
            path = shutil.which(cmd)
            if path:
                return path
        
        return None
    else:
        # 非打包环境，直接使用 sys.executable
        return sys.executable


def use_shared_python_env() -> bool:
    value = str(os.environ.get("SAGE_SHARED_PYTHON_ENV", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_shared_python_env_dir() -> str:
    custom_path = os.environ.get("SAGE_SHARED_PYTHON_ENV_DIR")
    if custom_path:
        return os.path.abspath(os.path.expanduser(custom_path))
    return os.path.join(os.path.expanduser("~"), ".sage", ".sage_py_env")


def resolve_python_venv_dir(workspace_path: Optional[str]) -> Optional[str]:
    if use_shared_python_env():
        return get_shared_python_env_dir()
    if not workspace_path:
        return None
    return os.path.join(workspace_path, ".sandbox", "venv")


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

def ensure_list(content: Union[str, List[Any]], separator: str = None) -> List[Any]:
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
        if content.startswith('[') and content.endswith(']'):
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
    if ',' in content:
        return [item.strip() for item in content.split(',') if item.strip()]
    
    # Auto-detect: if space exists, assume space-separated
    if ' ' in content:
        return [item.strip() for item in content.split(' ') if item.strip()]

    # 4. Fallback: return as single item list
    return [content]
