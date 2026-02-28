"""
配置相关, 支持命令行参数、环境变量、默认值
"""

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ===== 全局启动参数（统一存放于此） =====
_GLOBAL_STARTUP_CONFIG: Optional[Any] = None


@dataclass
class StartupConfig:
    """启动参数结构体，优先级：命令行 > 环境变量 > 默认值"""

    # Server
    port: int = 8080
    logs_dir: str = "logs"
    workspace: str = "agent_workspace"

    # DB
    db_type: str = "file"  # file | memory
    db_path: str = "./data/"  # file 模式为目录；memory 为忽略

    # Presets
    preset_mcp_config: str = "mcp_setting.json"
    preset_running_config: str = "agent_setting.json"

    # LLM defaults
    default_llm_api_key: str = ""
    default_llm_api_base_url: str = "https://api.deepseek.com/v1"
    default_llm_model_name: str = "deepseek-chat"
    default_llm_max_tokens: int = 4096
    default_llm_temperature: float = 0.2
    default_llm_max_model_len: int = 54000
    default_llm_top_p: float = 0.9
    default_llm_presence_penalty: float = 0.0

    # Context Budget Defaults
    context_history_ratio: float = 0.2
    context_active_ratio: float = 0.3
    context_max_new_message_ratio: float = 0.5
    context_recent_turns: int = 0
    
    # auth
    jwt_key: str = "sage_dev_jwt_secret_key_change_me_in_prod_v1"
    jwt_expire_hours: int = 24
    refresh_token_secret: str = "sage_dev_refresh_secret_key_change_me_in_prod_v1"

    # Embedding
    embed_api_key: Optional[str] = None
    embed_base_url: Optional[str] = None
    embed_model: str = "text-embedding-3-large"
    embed_dims: int = 1024

    # S3
    s3_endpoint: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_secure: bool = False
    s3_bucket_name: Optional[str] = None
    s3_public_base_url: Optional[str] = None


class ENV:
    # 新版 LLM 相关
    DEFAULT_LLM_API_KEY = "SAGE_DEFAULT_LLM_API_KEY"
    DEFAULT_LLM_API_BASE_URL = "SAGE_DEFAULT_LLM_API_BASE_URL"
    DEFAULT_LLM_MODEL_NAME = "SAGE_DEFAULT_LLM_MODEL_NAME"
    DEFAULT_LLM_MAX_TOKENS = "SAGE_DEFAULT_LLM_MAX_TOKENS"
    DEFAULT_LLM_TEMPERATURE = "SAGE_DEFAULT_LLM_TEMPERATURE"
    DEFAULT_LLM_MAX_MODEL_LEN = "SAGE_DEFAULT_LLM_MAX_MODEL_LEN"
    DEFAULT_LLM_TOP_P = "SAGE_DEFAULT_LLM_TOP_P"
    DEFAULT_LLM_PRESENCE_PENALTY = "SAGE_DEFAULT_LLM_PRESENCE_PENALTY"

    # Context Budget
    CONTEXT_HISTORY_RATIO = "SAGE_CONTEXT_HISTORY_RATIO"
    CONTEXT_ACTIVE_RATIO = "SAGE_CONTEXT_ACTIVE_RATIO"
    CONTEXT_MAX_NEW_MESSAGE_RATIO = "SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO"
    CONTEXT_RECENT_TURNS = "SAGE_CONTEXT_RECENT_TURNS"

    # 服务器与运行配置
    PORT = "SAGE_PORT"
    PRESET_MCP_CONFIG = "SAGE_MCP_CONFIG_PATH"
    PRESET_RUNNING_CONFIG = "SAGE_PRESET_RUNNING_CONFIG_PATH"
    WORKSPACE = "SAGE_WORKSPACE_PATH"
    LOGS_DIR = "SAGE_LOGS_DIR_PATH"

    # 数据库
    DB_TYPE = "SAGE_DB_TYPE"
    DB_PATH = "SAGE_DB_PATH"

    # 旧版 LLM 环境变量兜底
    LEGACY_LLM_API_KEY = "LLM_API_KEY"
    LEGACY_LLM_API_BASE_URL = "LLM_API_BASE_URL"
    LEGACY_LLM_MODEL_NAME = "LLM_MODEL_NAME"

    # S3
    S3_ENDPOINT = "SAGE_S3_ENDPOINT"
    S3_ACCESS_KEY = "SAGE_S3_ACCESS_KEY"
    S3_SECRET_KEY = "SAGE_S3_SECRET_KEY"
    S3_SECURE = "SAGE_S3_SECURE"
    S3_BUCKET_NAME = "SAGE_S3_BUCKET_NAME"
    S3_PUBLIC_BASE_URL = "SAGE_S3_PUBLIC_BASE_URL"

    # Knowledge Base MCP 接口
    KB_MCP_URL = "SAGE_KB_MCP_URL"
    KB_MCP_API_KEY = "SAGE_KB_MCP_API_KEY"

    JWT_KEY = "SAGE_JWT_KEY"
    JWT_EXPIRE_HOURS = "SAGE_JWT_EXPIRE_HOURS"
    REFRESH_TOKEN_SECRET = "SAGE_REFRESH_TOKEN_SECRET"

    EMBEDDING_API_KEY = "SAGE_EMBEDDING_API_KEY"
    EMBEDDING_BASE_URL = "SAGE_EMBEDDING_BASE_URL"
    EMBEDDING_MODEL = "SAGE_EMBEDDING_MODEL"
    EMBEDDING_DIMS = "SAGE_EMBEDDING_DIMS"


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


def env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: Optional[float] = None) -> Optional[float]:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes", "y", "t")


def pick_str(
    arg_val: Optional[str], env_name: str, default: Optional[str] = None
) -> Optional[str]:
    return arg_val if arg_val is not None else env_str(env_name, default)


def pick_int(
    arg_val: Optional[int], env_name: str, default: Optional[int] = None
) -> Optional[int]:
    return arg_val if arg_val is not None else env_int(env_name, default)


def pick_float(
    arg_val: Optional[float], env_name: str, default: Optional[float] = None
) -> Optional[float]:
    return arg_val if arg_val is not None else env_float(env_name, default)


def pick_bool(arg_flag: bool, env_name: str, default: bool = False) -> bool:
    return True if arg_flag else env_bool(env_name, default)


def pick_str_list(
    arg_val: Optional[str], env_name: str, default: Optional[list[str]] = None
) -> Optional[list[str]]:
    val_str = pick_str(arg_val, env_name)
    if val_str:
        return [x.strip() for x in val_str.split(",") if x.strip()]
    return default


def pick_json_list(
    arg_val: Optional[str], env_name: str, default: Optional[List[Dict[str, str]]] = None
) -> Optional[List[Dict[str, str]]]:
    val_str = pick_str(arg_val, env_name)
    if val_str:
        try:
            val = json.loads(val_str)
            if isinstance(val, list):
                return val
        except json.JSONDecodeError:
            pass
    return default


def pick_json_dict_list(
    arg_val: Optional[str], env_name: str, default: Optional[Dict[str, List[Dict[str, str]]]] = None
) -> Optional[Dict[str, List[Dict[str, str]]]]:
    val_str = pick_str(arg_val, env_name)
    if val_str:
        try:
            val = json.loads(val_str)
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            pass
    return default



def build_startup_config() -> StartupConfig:
    cfg = StartupConfig()
    return cfg

def get_startup_config() -> StartupConfig:
    return _GLOBAL_STARTUP_CONFIG

def init_startup_config() -> StartupConfig:
    global _GLOBAL_STARTUP_CONFIG
    cfg = build_startup_config()
    _GLOBAL_STARTUP_CONFIG = cfg
    return cfg
