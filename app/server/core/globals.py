"""
全局变量管理模块

统一管理系统中的所有全局变量，包括服务实例、配置参数等
"""

from typing import Any, Dict, Optional

from sagents.tool.tool_manager import ToolManager

_GLOBAL_TOOL_MANAGER: Optional[ToolManager] = None  # 工具管理器
_GLOBAL_ACTIVE_SESSION: Dict[str, Dict[str, Any]] = {}  # 活跃会话映射


def get_tool_manager():
    """获取工具管理器"""
    global _GLOBAL_TOOL_MANAGER
    return _GLOBAL_TOOL_MANAGER


def set_tool_manager(tm: ToolManager):
    """设置工具管理器"""
    global _GLOBAL_TOOL_MANAGER
    _GLOBAL_TOOL_MANAGER = tm


def get_all_active_sessions_service_map() -> Dict[str, Dict[str, Any]]:
    """获取所有活跃会话服务映射"""
    return _GLOBAL_ACTIVE_SESSION


def set_all_active_sessions_service_map(session_map: Dict[str, Dict[str, Any]]):
    """设置所有活跃会话服务映射"""
    global _GLOBAL_ACTIVE_SESSION
    _GLOBAL_ACTIVE_SESSION = session_map
