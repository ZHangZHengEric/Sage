"""
沙箱工具函数

提供统一的接口来访问沙箱功能，避免在工具函数中直接判断沙箱是否存在。
"""
import os
from typing import Optional
from sagents.utils.common_utils import get_system_python_path


def get_sandbox_python_path(session_id: Optional[str] = None) -> Optional[str]:
    """
    获取沙箱的 Python 路径。

    优先级：
    1. 环境变量 SANDBOX_PYTHON_PATH（由沙箱设置）
    2. 通过 session_id 获取沙箱实例
    3. 返回系统 Python（使用 get_system_python_path 处理 PyInstaller 打包环境）
    """
    python_path = os.environ.get('SANDBOX_PYTHON_PATH')
    if python_path:
        return python_path

    if session_id:
        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if session and session.session_context and hasattr(session.session_context, 'agent_workspace_sandbox') and session.session_context.agent_workspace_sandbox:
            return session.session_context.agent_workspace_sandbox.get_venv_python()

    # 使用 get_system_python_path 处理 PyInstaller 打包环境
    return get_system_python_path()


def get_sandbox_workdir(workdir: Optional[str], session_id: Optional[str] = None) -> Optional[str]:
    """
    获取沙箱的工作目录（宿主机路径）。
    """
    if not workdir:
        return None
    
    if session_id:
        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if session and session.session_context:
            if hasattr(session.session_context, 'agent_workspace_sandbox') and session.session_context.agent_workspace_sandbox:
                fs = session.session_context.agent_workspace_sandbox.file_system
                if hasattr(fs, 'map_text_to_host'):
                    return fs.map_text_to_host(workdir)
            if hasattr(session.session_context, 'agent_workspace'):
                ws = session.session_context.agent_workspace
                if isinstance(ws, str):
                    return ws
                elif hasattr(ws, 'host_path'):
                    return ws.host_path
    
    return workdir


def get_sandbox_host_path(session_id: Optional[str] = None) -> Optional[str]:
    """获取沙箱的 host_path。"""
    if not session_id:
        return None
    
    from sagents.session_runtime import get_global_session_manager
    session_manager = get_global_session_manager()
    session = session_manager.get(session_id)
    if session and session.session_context and hasattr(session.session_context, 'agent_workspace_sandbox'):
        ws = session.session_context.agent_workspace_sandbox.file_system
        if hasattr(ws, 'host_path'):
            return ws.host_path
    return None


def get_sandbox_venv_bin(session_id: Optional[str] = None) -> Optional[str]:
    """获取沙箱的 venv/bin 路径。"""
    venv_path = os.environ.get('VIRTUAL_ENV')
    if venv_path:
        return os.path.join(venv_path, 'bin')
    
    if session_id:
        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if session and session.session_context and hasattr(session.session_context, 'agent_workspace_sandbox') and session.session_context.agent_workspace_sandbox:
            venv_dir = session.session_context.agent_workspace_sandbox.venv_dir
            if venv_dir:
                return os.path.join(venv_dir, 'bin')
    return None


def is_in_sandbox() -> bool:
    """检查当前是否在沙箱中运行。"""
    return 'SANDBOX_PYTHON_PATH' in os.environ or 'VIRTUAL_ENV' in os.environ
