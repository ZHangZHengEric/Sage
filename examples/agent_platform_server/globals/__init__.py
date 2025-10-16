"""
全局变量管理包

提供统一的全局变量管理接口
"""

from .variables import (
    # 全局变量
    default_stream_service,
    all_active_sessions_service_map,
    tool_manager,
    default_model_client,
    server_args,
    
    # 访问器函数
    get_default_stream_service,
    set_default_stream_service,
    get_all_active_sessions_service_map,
    set_all_active_sessions_service_map,
    get_tool_manager,
    set_tool_manager,
    get_default_model_client,
    set_default_model_client,
    get_server_args,
    set_server_args,
    
    # 初始化和清理函数
    init_global_variables,
    cleanup_global_variables
)

__all__ = [
    # 全局变量
    'default_stream_service',
    'all_active_sessions_service_map',
    'tool_manager',
    'default_model_client',
    'server_args',
    
    # 访问器函数
    'get_default_stream_service',
    'set_default_stream_service',
    'get_all_active_sessions_service_map',
    'set_all_active_sessions_service_map',
    'get_tool_manager',
    'set_tool_manager',
    'get_default_model_client',
    'set_default_model_client',
    'get_server_args',
    'set_server_args',
    
    # 初始化和清理函数
    'init_global_variables',
    'cleanup_global_variables'
]