"""
沙箱工具函数

提供统一的接口来访问沙箱功能，避免在工具函数中直接判断沙箱是否存在。
"""
import os
import sys
from typing import Optional


def get_sandbox_python_path(session_id: Optional[str] = None) -> Optional[str]:
    """
    获取沙箱的 Python 路径。
    
    优先级：
    1. 环境变量 SANDBOX_PYTHON_PATH（由沙箱设置）
    2. 通过 session_id 获取沙箱实例
    3. 返回系统 Python
    """
    python_path = os.environ.get('SANDBOX_PYTHON_PATH')
    if python_path:
        return python_path
    
    if session_id:
        from sagents.context.session_context import get_session_context
        session_context = get_session_context(session_id)
        if session_context and hasattr(session_context, 'sandbox') and session_context.sandbox:
            return session_context.sandbox.get_venv_python()
    
    return sys.executable


def get_sandbox_workdir(workdir: Optional[str], session_id: Optional[str] = None) -> Optional[str]:
    """
    获取沙箱的工作目录（宿主机路径）。
    """
    if not workdir:
        return None
    
    if session_id:
        from sagents.context.session_context import get_session_context
        session_context = get_session_context(session_id)
        if session_context:
            if hasattr(session_context, 'sandbox') and session_context.sandbox:
                fs = session_context.sandbox.file_system
                if hasattr(fs, 'map_text_to_host'):
                    return fs.map_text_to_host(workdir)
            if hasattr(session_context, 'agent_workspace'):
                ws = session_context.agent_workspace
                if isinstance(ws, str):
                    return ws
                elif hasattr(ws, 'host_path'):
                    return ws.host_path
    
    return workdir


def get_sandbox_host_path(session_id: Optional[str] = None) -> Optional[str]:
    """获取沙箱的 host_path。"""
    if not session_id:
        return None
    
    from sagents.context.session_context import get_session_context
    session_context = get_session_context(session_id)
    if session_context and hasattr(session_context, 'agent_workspace'):
        ws = session_context.agent_workspace
        if hasattr(ws, 'host_path'):
            return ws.host_path
    return None


def get_sandbox_venv_bin(session_id: Optional[str] = None) -> Optional[str]:
    """获取沙箱的 venv/bin 路径。"""
    venv_path = os.environ.get('VIRTUAL_ENV')
    if venv_path:
        return os.path.join(venv_path, 'bin')
    
    if session_id:
        from sagents.context.session_context import get_session_context
        session_context = get_session_context(session_id)
        if session_context and hasattr(session_context, 'sandbox') and session_context.sandbox:
            venv_dir = session_context.sandbox.venv_dir
            if venv_dir:
                return os.path.join(venv_dir, 'bin')
    return None


def is_in_sandbox() -> bool:
    """检查当前是否在沙箱中运行。"""
    return 'SANDBOX_PYTHON_PATH' in os.environ or 'VIRTUAL_ENV' in os.environ
