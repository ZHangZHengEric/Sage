"""
全局变量管理模块

统一管理系统中的所有全局变量，包括服务实例、配置参数等
"""

import os
import json
import traceback
from typing import Optional, Dict, Any
from openai import OpenAI
from sagents.tool.tool_manager import ToolManager
from sagents.utils.logger import logger

# 服务相关全局变量
default_stream_service = None  # SageStreamService实例
all_active_sessions_service_map: Dict[str, Dict[str, Any]] = {}  # 活跃会话映射
tool_manager: Optional[ToolManager] = None  # 工具管理器
default_model_client: Optional[OpenAI] = None  # 默认模型客户端

# 配置相关全局变量
server_args = None  # 服务器启动参数
database_manager = None  # 数据库管理器


def get_default_stream_service():
    """获取默认流式服务实例"""
    global default_stream_service
    return default_stream_service


def set_default_stream_service(service):
    """设置默认流式服务实例"""
    global default_stream_service
    default_stream_service = service


def get_all_active_sessions_service_map():
    """获取活跃会话映射"""
    global all_active_sessions_service_map
    return all_active_sessions_service_map


def set_all_active_sessions_service_map(sessions_map):
    """设置活跃会话映射"""
    global all_active_sessions_service_map
    all_active_sessions_service_map = sessions_map


def get_tool_manager():
    """获取工具管理器"""
    global tool_manager
    return tool_manager


def set_tool_manager(tm):
    """设置工具管理器"""
    global tool_manager
    tool_manager = tm


def get_default_model_client():
    """获取默认模型客户端"""
    global default_model_client
    return default_model_client


def set_default_model_client(client):
    """设置默认模型客户端"""
    global default_model_client
    default_model_client = client


def get_server_args():
    """获取服务器启动参数"""
    global server_args
    return server_args


def set_server_args(args):
    """设置服务器启动参数"""
    global server_args
    server_args = args


def get_database_manager():
    """获取数据库管理器"""
    global database_manager
    return database_manager


def set_database_manager(db_manager):
    """设置数据库管理器"""
    global database_manager
    database_manager = db_manager


async def initialize_tool_manager():
    """初始化工具管理器"""
    try:
        tool_manager_instance = ToolManager()
        # 设置 MCP 配置路径
        tool_manager_instance._mcp_setting_path = os.environ.get('SAGE_MCP_CONFIG_PATH', 'mcp_setting.json')
        await tool_manager_instance.initialize()
        return tool_manager_instance
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        logger.error(traceback.format_exc())
        return None


async def initialize_system(args):
    """初始化系统"""
    global default_stream_service, tool_manager, server_args,default_model_client, database_manager
    
    # 设置服务器参数
    server_args = args
    
    logger.info("正在初始化 Sage Platform Server...")
    
    try:
        # 初始化模型客户端
        if server_args.default_llm_api_key:
            logger.debug(f"默认 API 密钥: {server_args.default_llm_api_key}...")
            logger.debug(f"默认 API 基础 URL: {server_args.default_llm_api_base_url}...")
            default_model_client = OpenAI(
                api_key=server_args.default_llm_api_key,
                base_url=server_args.default_llm_api_base_url
            )
            default_model_client.model = server_args.default_llm_model_name
            logger.info(f"默认模型客户端初始化成功: {server_args.default_llm_model_name}")
            from handler import SageStreamService
            # 从配置中构建模型配置字典
            model_config_dict = {
                'model': server_args.default_llm_model_name,
                'max_tokens': server_args.default_llm_max_tokens,
                'temperature': server_args.default_llm_temperature
            }

            # 读取预设运行配置（兼容单个与多个 agent）
            preset_running_config = load_default_preset_running_config(server_args.preset_running_config)

            default_stream_service = SageStreamService(
                model=default_model_client,
                model_config=model_config_dict,
                tool_manager=tool_manager,
                preset_running_config=preset_running_config,
                workspace=server_args.workspace,
                memory_root=server_args.memory_root,
                max_model_len=server_args.default_llm_max_model_len
            )
            logger.info("默认 SageStreamService 初始化成功")
        else:
            logger.warning("未配置默认 API 密钥，某些功能可能不可用")
        # 初始化数据库
        from database.database_manager import DatabaseManager
        database_manager = DatabaseManager(
            db_type=server_args.db_type,
            db_path=server_args.db_path
        )
        await database_manager.initialize(
            preset_mcp_config=server_args.preset_mcp_config,
            preset_running_config=server_args.preset_running_config
        )
        logger.info(f"数据库管理器初始化成功 (模式: {server_args.db_type})")
        # 初始化工具管理器
        tool_manager = await initialize_tool_manager()
        logger.info("工具管理器初始化成功")
        # 验证MCP服务器列表
        if database_manager and tool_manager:
            await database_manager.validate_and_cleanup_mcp_servers(tool_manager)
 
    except Exception as e:
        logger.error(f"系统初始化失败: {e}")
        logger.error(traceback.format_exc())


def init_global_variables():
    """初始化全局变量"""
    global default_stream_service, all_active_sessions_service_map, tool_manager, server_args, database_manager
    
    # 重置所有全局变量
    default_stream_service = None
    all_active_sessions_service_map = {}
    tool_manager = None
    database_manager = None
    # server_args 通常在启动时设置，这里不重置


async def cleanup_system():
    """清理系统资源"""
    global default_stream_service, all_active_sessions_service_map, tool_manager, server_args, default_model_client, database_manager
    
    logger.debug("正在清理系统资源...")
    
    try:
        # 清理所有活跃会话
        for session_id, session_info in all_active_sessions_service_map.items():
            try:
                if 'service' in session_info:
                    # 这里可以添加会话清理逻辑
                    pass
            except Exception as e:
                logger.error(f"清理会话 {session_id} 失败: {e}")
        
        # 清理流式服务
        if default_stream_service:
            # 这里可以添加流式服务的清理逻辑
            default_stream_service = None
        
        # 清理会话映射
        all_active_sessions_service_map.clear()
        
        # 清理工具管理器
        if tool_manager:
            # 这里可以添加工具管理器的清理逻辑
            tool_manager = None
        
        # 清理模型客户端
        if default_model_client:
            default_model_client = None
        
        # 清理数据库管理器
        if database_manager:
            try:
                await database_manager.close()
            except Exception as e:
                logger.error(f"数据库管理器清理失败: {e}")
            database_manager = None
        
        logger.debug("系统资源清理完成")
        
    except Exception as e:
        logger.error(f"系统清理失败: {e}")
        logger.error(traceback.format_exc())


def cleanup_global_variables():
    """清理全局变量"""
    global default_stream_service, all_active_sessions_service_map, tool_manager, server_args, default_model_client, database_manager
    
    # 清理会话映射
    all_active_sessions_service_map.clear()
    
    # 清理其他变量
    default_stream_service = None
    tool_manager = None
    database_manager = None
    default_model_client = None
    server_args = None

# 通用读取预设运行配置（兼容单个与多个 agent）
def load_default_preset_running_config(config_path: Optional[str]) -> Dict[str, Any]:
    try:
        if not config_path:
            return {}
        if not os.path.exists(config_path):
            logger.warning(f"预设Agent配置文件不存在: {config_path}")
            return {}
        with open(config_path, 'r') as f:
            raw_config = json.load(f)
        if isinstance(raw_config, dict):
            if 'systemPrefix' in raw_config or 'systemContext' in raw_config:
                # 旧格式（单个 agent）或已是默认结构
                return raw_config
            else:
                # 新格式（多个 agents），取第一个有效的作为默认
                for _, agent_cfg in raw_config.items():
                    if isinstance(agent_cfg, dict):
                        return agent_cfg
        logger.warning("预设Agent配置格式不正确，使用空配置")
        return {}
    except Exception as e:
        logger.error(f"读取预设Agent配置失败: {e}")
        return {}