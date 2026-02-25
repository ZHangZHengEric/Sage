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
    db_type: str = "file"  # file | memory | mysql
    db_path: str = "./data/"  # file 模式为目录；memory 为忽略；mysql 支持 DSN/JSON/ENV
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "sage.1234"
    mysql_database: str = "sage"
    mysql_charset: str = "utf8mb4"

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
    jwt_key: str = "123"
    jwt_expire_hours: int = 24
    refresh_token_secret: str = "123"

    # Embedding
    embed_api_key: Optional[str] = None
    embed_base_url: Optional[str] = None
    embed_model: str = "text-embedding-3-large"
    embed_dims: int = 1024

    # Elasticsearch
    es_url: Optional[str] = None
    es_api_key: Optional[str] = None
    es_username: Optional[str] = None
    es_password: Optional[str] = None

    # S3
    s3_endpoint: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_secure: bool = False
    s3_bucket_name: Optional[str] = None
    s3_public_base_url: Optional[str] = None

    # Trace
    trace_jaeger_endpoint: Optional[str] = None


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

    # Trace
    TRACE_JAEGER_URL = "SAGE_TRACE_JAEGER_URL"

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

    MYSQL_HOST = "SAGE_MYSQL_HOST"
    MYSQL_PORT = "SAGE_MYSQL_PORT"
    MYSQL_USER = "SAGE_MYSQL_USER"
    MYSQL_PASSWORD = "SAGE_MYSQL_PASSWORD"
    MYSQL_DATABASE = "SAGE_MYSQL_DATABASE"

    EMBEDDING_API_KEY = "SAGE_EMBEDDING_API_KEY"
    EMBEDDING_BASE_URL = "SAGE_EMBEDDING_BASE_URL"
    EMBEDDING_MODEL = "SAGE_EMBEDDING_MODEL"
    EMBEDDING_DIMS = "SAGE_EMBEDDING_DIMS"

    ES_URL = "SAGE_ELASTICSEARCH_URL"
    ES_API_KEY = "SAGE_ELASTICSEARCH_API_KEY"
    ES_USERNAME = "SAGE_ELASTICSEARCH_USERNAME"
    ES_PASSWORD = "SAGE_ELASTICSEARCH_PASSWORD"


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


def create_argument_parser():
    """创建命令行参数解析器，支持环境变量，优先级：指定入参 > 环境变量 > 默认值"""
    parser = argparse.ArgumentParser(description="Sage Stream Service")

    # 新格式参数
    parser.add_argument(
        "--default_llm_api_key",
        help=f"默认LLM API Key (环境变量: {ENV.DEFAULT_LLM_API_KEY})",
    )

    parser.add_argument(
        "--default_llm_api_base_url",
        help=f"默认LLM API Base (环境变量: {ENV.DEFAULT_LLM_API_BASE_URL})",
    )
    parser.add_argument(
        "--default_llm_model_name",
        help=f"默认LLM API Model (环境变量: {ENV.DEFAULT_LLM_MODEL_NAME})",
    )
    parser.add_argument(
        "--default_llm_max_tokens",
        type=int,
        help=f"默认LLM API Max Tokens (环境变量: {ENV.DEFAULT_LLM_MAX_TOKENS})",
    )
    parser.add_argument(
        "--default_llm_temperature",
        type=float,
        help=f"默认LLM API Temperature (环境变量: {ENV.DEFAULT_LLM_TEMPERATURE})",
    )
    parser.add_argument(
        "--default_llm_max_model_len",
        type=int,
        help=f"默认LLM 最大上下文 (环境变量: {ENV.DEFAULT_LLM_MAX_MODEL_LEN})",
    )
    parser.add_argument(
        "--default_llm_top_p",
        type=float,
        help=f"默认LLM API Top P (环境变量: {ENV.DEFAULT_LLM_TOP_P})",
    )
    parser.add_argument(
        "--default_llm_presence_penalty",
        type=float,
        help=f"默认LLM API Presence Penalty (环境变量: {ENV.DEFAULT_LLM_PRESENCE_PENALTY})",
    )
    parser.add_argument(
        "--context_history_ratio",
        type=float,
        help=f"历史消息比例 (环境变量: {ENV.CONTEXT_HISTORY_RATIO})",
    )
    parser.add_argument(
        "--context_active_ratio",
        type=float,
        help=f"活跃消息比例 (环境变量: {ENV.CONTEXT_ACTIVE_RATIO})",
    )
    parser.add_argument(
        "--context_max_new_message_ratio",
        type=float,
        help=f"新消息最大比例 (环境变量: {ENV.CONTEXT_MAX_NEW_MESSAGE_RATIO})",
    )
    parser.add_argument(
        "--context_recent_turns",
        type=int,
        help=f"最近对话轮数 (环境变量: {ENV.CONTEXT_RECENT_TURNS})",
    )
    parser.add_argument(
        "--port",
        type=int,
        help=f"Server Port (环境变量: {ENV.PORT})",
    )
    parser.add_argument(
        "--preset_mcp_config",
        help=f"MCP配置文件路径 (环境变量: {ENV.PRESET_MCP_CONFIG})",
    )
    parser.add_argument(
        "--preset_running_config",
        help=f"预设配置，system_context，以及workflow，与接口中传过来的合并使用 (环境变量: {ENV.PRESET_RUNNING_CONFIG})",
    )
    parser.add_argument(
        "--workspace",
        help=f"工作空间目录 (环境变量: {ENV.WORKSPACE})",
    )
    parser.add_argument(
        "--logs-dir",
        help=f"日志目录 (环境变量: {ENV.LOGS_DIR})",
    )


    # Embedding 配置
    parser.add_argument(
        "--embedding_api_key",
        help=f"Embedding API Key (环境变量: {ENV.EMBEDDING_API_KEY})",
    )
    parser.add_argument(
        "--embedding_base_url",
        help=f"Embedding Base URL (环境变量: {ENV.EMBEDDING_BASE_URL})",
    )
    parser.add_argument(
        "--embedding_model",
        help=f"Embedding Model (环境变量: {ENV.EMBEDDING_MODEL})",
    )
    parser.add_argument(
        "--embedding_dims",
        type=int,
        help=f"Embedding Dims (环境变量: {ENV.EMBEDDING_DIMS})",
    )

    # Elasticsearch 配置
    parser.add_argument(
        "--es_url",
        help=f"Elasticsearch URL (环境变量: {ENV.ES_URL})",
    )
    parser.add_argument(
        "--es_api_key",
        help=f"Elasticsearch API Key (环境变量: {ENV.ES_API_KEY})",
    )
    parser.add_argument(
        "--es_username",
        help=f"Elasticsearch Username (环境变量: {ENV.ES_USERNAME})",
    )
    parser.add_argument(
        "--es_password",
        help=f"Elasticsearch Password (环境变量: {ENV.ES_PASSWORD})",
    )

    # S3 配置
    parser.add_argument(
        "--s3_endpoint",
        help=f"S3 Endpoint (环境变量: {ENV.S3_ENDPOINT})",
    )
    parser.add_argument(
        "--s3_access_key",
        help=f"S3 Access Key (环境变量: {ENV.S3_ACCESS_KEY})",
    )
    parser.add_argument(
        "--s3_secret_key",
        help=f"S3 Secret Key (环境变量: {ENV.S3_SECRET_KEY})",
    )
    parser.add_argument(
        "--s3_secure",
        action="store_true",
        help=f"S3 使用 https (环境变量: {ENV.S3_SECURE})",
    )
    parser.add_argument(
        "--s3_bucket_name",
        help=f"S3 Bucket (环境变量: {ENV.S3_BUCKET_NAME})",
    )
    parser.add_argument(
        "--s3_public_base_url",
        help=f"S3 Public Base URL (环境变量: {ENV.S3_PUBLIC_BASE_URL})",
    )

    # Trace 配置
    parser.add_argument(
        "--trace_jaeger_endpoint",
        help=f"Jaeger OTLP Endpoint (http/grpc), e.g. http://localhost:4317 (环境变量: {ENV.TRACE_JAEGER_URL})",
    )

    # 数据库相关参数
    parser.add_argument(
        "--db_type",
        choices=["file", "memory", "mysql"],
        help=f"数据库类型：file、memory、mysql (环境变量: {ENV.DB_TYPE})",
    )
    parser.add_argument(
        "--db_path",
        help=f"数据库文件存储路径，仅在file模式下有效 (环境变量: {ENV.DB_PATH})",
    )

    # MySQL 连接参数
    parser.add_argument("--mysql_host")
    parser.add_argument("--mysql_port", type=int)
    parser.add_argument("--mysql_user")
    parser.add_argument("--mysql_password")
    parser.add_argument("--mysql_database")

    return parser


def build_startup_config() -> StartupConfig:
    """解析命令行并按优先级合并环境变量与默认值，得到结构化启动配置"""
    parser = create_argument_parser()
    args = parser.parse_args()

    cfg = StartupConfig(
        port=pick_int(args.port, ENV.PORT, StartupConfig.port),
        logs_dir=pick_str(args.logs_dir, ENV.LOGS_DIR, StartupConfig.logs_dir),
        workspace=pick_str(args.workspace, ENV.WORKSPACE, StartupConfig.workspace),

        db_type=pick_str(args.db_type, ENV.DB_TYPE, StartupConfig.db_type),
        db_path=pick_str(args.db_path, ENV.DB_PATH, StartupConfig.db_path),
        mysql_host=pick_str(args.mysql_host, ENV.MYSQL_HOST, StartupConfig.mysql_host),
        mysql_port=pick_int(args.mysql_port, ENV.MYSQL_PORT, StartupConfig.mysql_port),
        mysql_user=pick_str(args.mysql_user, ENV.MYSQL_USER, StartupConfig.mysql_user),
        mysql_password=pick_str(
            args.mysql_password, ENV.MYSQL_PASSWORD, StartupConfig.mysql_password
        ),
        mysql_database=pick_str(
            args.mysql_database, ENV.MYSQL_DATABASE, StartupConfig.mysql_database
        ),
        mysql_charset=StartupConfig.mysql_charset,
        preset_mcp_config=pick_str(
            args.preset_mcp_config,
            ENV.PRESET_MCP_CONFIG,
            StartupConfig.preset_mcp_config,
        ),
        preset_running_config=pick_str(
            args.preset_running_config,
            ENV.PRESET_RUNNING_CONFIG,
            StartupConfig.preset_running_config,
        ),
        default_llm_api_key=pick_str(
            args.default_llm_api_key,
            ENV.DEFAULT_LLM_API_KEY,
            StartupConfig.default_llm_api_key,
        ),
        default_llm_api_base_url=pick_str(
            args.default_llm_api_base_url,
            ENV.DEFAULT_LLM_API_BASE_URL,
            StartupConfig.default_llm_api_base_url,
        ),
        default_llm_model_name=pick_str(
            args.default_llm_model_name,
            ENV.DEFAULT_LLM_MODEL_NAME,
            StartupConfig.default_llm_model_name,
        ),
        default_llm_max_tokens=pick_int(
            args.default_llm_max_tokens,
            ENV.DEFAULT_LLM_MAX_TOKENS,
            StartupConfig.default_llm_max_tokens,
        ),
        default_llm_temperature=pick_float(
            args.default_llm_temperature,
            ENV.DEFAULT_LLM_TEMPERATURE,
            StartupConfig.default_llm_temperature,
        ),
        default_llm_max_model_len=pick_int(
            args.default_llm_max_model_len,
            ENV.DEFAULT_LLM_MAX_MODEL_LEN,
            StartupConfig.default_llm_max_model_len,
        ),
        default_llm_top_p=pick_float(
            args.default_llm_top_p,
            ENV.DEFAULT_LLM_TOP_P,
            StartupConfig.default_llm_top_p,
        ),
        default_llm_presence_penalty=pick_float(
            args.default_llm_presence_penalty,
            ENV.DEFAULT_LLM_PRESENCE_PENALTY,
            StartupConfig.default_llm_presence_penalty,
        ),
        context_history_ratio=pick_float(
            args.context_history_ratio,
            ENV.CONTEXT_HISTORY_RATIO,
            StartupConfig.context_history_ratio,
        ),
        context_active_ratio=pick_float(
            args.context_active_ratio,
            ENV.CONTEXT_ACTIVE_RATIO,
            StartupConfig.context_active_ratio,
        ),
        context_max_new_message_ratio=pick_float(
            args.context_max_new_message_ratio,
            ENV.CONTEXT_MAX_NEW_MESSAGE_RATIO,
            StartupConfig.context_max_new_message_ratio,
        ),
        context_recent_turns=pick_int(
            args.context_recent_turns,
            ENV.CONTEXT_RECENT_TURNS,
            StartupConfig.context_recent_turns,
        ),
        embed_api_key=pick_str(
            args.embedding_api_key, ENV.EMBEDDING_API_KEY, StartupConfig.embed_api_key
        ),
        embed_base_url=pick_str(
            args.embedding_base_url,
            ENV.EMBEDDING_BASE_URL,
            StartupConfig.embed_base_url,
        ),
        embed_model=pick_str(
            args.embedding_model, ENV.EMBEDDING_MODEL, StartupConfig.embed_model
        ),
        embed_dims=pick_int(
            args.embedding_dims, ENV.EMBEDDING_DIMS, StartupConfig.embed_dims
        ),
        es_url=pick_str(args.es_url, ENV.ES_URL, StartupConfig.es_url),
        es_api_key=pick_str(args.es_api_key, ENV.ES_API_KEY, StartupConfig.es_api_key),
        es_username=pick_str(
            args.es_username, ENV.ES_USERNAME, StartupConfig.es_username
        ),
        es_password=pick_str(
            args.es_password, ENV.ES_PASSWORD, StartupConfig.es_password
        ),
        s3_endpoint=pick_str(
            args.s3_endpoint, ENV.S3_ENDPOINT, StartupConfig.s3_endpoint
        ),
        s3_access_key=pick_str(
            args.s3_access_key, ENV.S3_ACCESS_KEY, StartupConfig.s3_access_key
        ),
        s3_secret_key=pick_str(
            args.s3_secret_key, ENV.S3_SECRET_KEY, StartupConfig.s3_secret_key
        ),
        s3_secure=pick_bool(
            args.s3_secure, ENV.S3_SECURE, StartupConfig.s3_secure
        ),
        s3_bucket_name=pick_str(
            args.s3_bucket_name,
            ENV.S3_BUCKET_NAME,
            StartupConfig.s3_bucket_name,
        ),
        s3_public_base_url=pick_str(
            args.s3_public_base_url,
            ENV.S3_PUBLIC_BASE_URL,
            StartupConfig.s3_public_base_url,
        ),
        trace_jaeger_endpoint=pick_str(
            args.trace_jaeger_endpoint,
            ENV.TRACE_JAEGER_URL,
            StartupConfig.trace_jaeger_endpoint,
        ),
    )
    # 规范化路径
    if cfg.workspace:
        cfg.workspace = os.path.abspath(cfg.workspace)
        os.makedirs(cfg.workspace, exist_ok=True)
    if cfg.logs_dir:
        cfg.logs_dir = os.path.abspath(cfg.logs_dir)
        os.makedirs(cfg.logs_dir, exist_ok=True)
    if cfg.db_type == "file" and cfg.db_path:
        cfg.db_path = os.path.abspath(cfg.db_path)

    return cfg


def get_startup_config() -> StartupConfig:
    return _GLOBAL_STARTUP_CONFIG


def init_startup_config() -> StartupConfig:
    global _GLOBAL_STARTUP_CONFIG
    cfg = build_startup_config()
    _GLOBAL_STARTUP_CONFIG = cfg
    return cfg
