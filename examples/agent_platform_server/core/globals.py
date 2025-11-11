"""
全局变量管理模块

统一管理系统中的所有全局变量，包括服务实例、配置参数等
"""

import traceback
from typing import Optional
from openai import OpenAI
from sagents.tool.tool_manager import ToolManager
from sagents.utils.logger import logger
from dataclasses import dataclass
from models.session_manager import SessionManager
import asyncio
from common.exceptions import SageHTTPException
from config.settings import StartupConfig

_GLOBAL_TOOL_MANAGER: Optional[ToolManager] = None  # 工具管理器
_GLOBAL_MODEL_CLIENT: Optional[OpenAI] = None  # 默认模型客户端
_GLOBAL_STARTUP_CONFIG: Optional[StartupConfig] = None  # 服务器启动参数
_GLOBAL_DB: Optional[SessionManager] = None  # 全局数据库管理器实例
_GLOBAL_DB_INIT_LOCK = asyncio.Lock()  # 数据库初始化锁，确保单例初始化
_GLOBAL_ACTIVE_SESSION: Dict[str, Dict[str, Any]] = {}  # 活跃会话映射


async def get_global_db() -> SessionManager:
    """获取全局数据库管理器实例。

    要求在项目启动阶段通过 `set_global_db()` 预先设置全局实例。
    若未设置则直接抛出错误，避免在运行时隐式初始化。
    """
    global _GLOBAL_DB
    if _GLOBAL_DB is None:
        raise SageHTTPException(
            status_code=500,
            detail="全局数据库管理器未设置",
            error_detail="请在项目启动时调用 set_global_db() 设置全局数据库管理器",
        )
    return _GLOBAL_DB


def set_global_db(db: SessionManager):
    """设置全局数据库管理器实例（可用于测试或自定义配置）。"""
    global _GLOBAL_DB
    _GLOBAL_DB = db


def get_startup_config():
    """获取服务器启动参数"""
    global _GLOBAL_STARTUP_CONFIG
    return _GLOBAL_STARTUP_CONFIG


def set_startup_config(cfg: StartupConfig):
    """设置服务器启动参数"""
    global _GLOBAL_STARTUP_CONFIG
    _GLOBAL_STARTUP_CONFIG = cfg


def get_tool_manager():
    """获取工具管理器"""
    global _GLOBAL_TOOL_MANAGER
    return _GLOBAL_TOOL_MANAGER


def set_tool_manager(tm: ToolManager):
    """设置工具管理器"""
    global _GLOBAL_TOOL_MANAGER
    _GLOBAL_TOOL_MANAGER = tm


def get_default_model_client():
    """获取默认模型客户端"""
    global _GLOBAL_MODEL_CLIENT
    return _GLOBAL_MODEL_CLIENT


def set_default_model_client(client: OpenAI):
    """设置默认模型客户端"""
    global _GLOBAL_MODEL_CLIENT
    _GLOBAL_MODEL_CLIENT = client


def get_all_active_sessions_service_map() -> Dict[str, Dict[str, Any]]:
    """获取所有活跃会话服务映射"""
    return _GLOBAL_ACTIVE_SESSION


def set_all_active_sessions_service_map(session_map: Dict[str, Dict[str, Any]]):
    """设置所有活跃会话服务映射"""
    global _GLOBAL_ACTIVE_SESSION
    _GLOBAL_ACTIVE_SESSION = session_map


async def initialize_tool_manager():
    """初始化工具管理器"""
    try:
        tool_manager_instance = ToolManager()
        set_tool_manager(tool_manager_instance)
        return tool_manager_instance
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        logger.error(traceback.format_exc())
        return None


async def initialize_default_model_client():
    """初始化默认模型客户端"""
    config = get_startup_config()
    try:
        logger.debug(f"默认 API 密钥: {config.default_llm_api_key}...")
        logger.debug(f"默认 API 基础 URL: {config.default_llm_api_base_url}...")
        default_model_client = OpenAI(
            api_key=config.default_llm_api_key,
            base_url=config.default_llm_api_base_url,
        )
        default_model_client.model = config.default_llm_model_name
        set_default_model_client(default_model_client)
        return default_model_client
    except Exception as e:
        logger.error(f"默认模型客户端初始化失败: {e}")
        logger.error(traceback.format_exc())
        return None


async def initialize_global_db():
    """初始化全局数据库管理器"""
    config = get_startup_config()
    try:
        db_manager = SessionManager(db_type=config.db_type, db_path=config.db_path)
        await db_manager.init_conn()
        set_global_db(db_manager)
        await db_manager.init_data(
            preset_mcp_config=config.preset_mcp_config,
            preset_agent_config=config.preset_running_config,
        )
        return db_manager
    except Exception as e:
        logger.error(f"全局数据库管理器初始化失败: {e}")
        logger.error(traceback.format_exc())
        return None


async def close_global_db():
    """关闭全局数据库管理器"""
    db_manager = get_global_db()
    if db_manager:
        db_manager.close()
        set_global_db(None)


async def close_default_model_client():
    """关闭默认模型客户端"""
    default_model_client = get_default_model_client()
    if default_model_client:
        default_model_client.close()
        set_default_model_client(None)


async def close_tool_manager():
    """关闭工具管理器"""
    tool_manager = get_tool_manager()
    if tool_manager:
        set_tool_manager(None)
