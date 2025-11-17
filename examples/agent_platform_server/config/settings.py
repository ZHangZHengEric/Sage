"""
配置相关, 支持命令行参数、环境变量、默认值
"""

import os
import argparse
from dataclasses import dataclass
from typing import Optional, Any

# ===== 全局启动参数（统一存放于此） =====
_GLOBAL_STARTUP_CONFIG: Optional[Any] = None


@dataclass
class StartupConfig:
    """启动参数结构体，优先级：命令行 > 环境变量 > 默认值"""

    # Server
    port: int = 8001
    daemon: bool = False
    pid_file: str = "sage_stream.pid"
    logs_dir: str = "logs"
    workspace: str = "agent_workspace"
    memory_root: Optional[str] = None
    force_summary: bool = False

    # DB
    db_type: str = "file"  # file | memory | mysql
    db_path: str = "./data/"  # file 模式为目录；memory 为忽略；mysql 支持 DSN/JSON/ENV
    mysql_host: Optional[str] = None
    mysql_port: Optional[int] = None
    mysql_user: Optional[str] = None
    mysql_password: Optional[str] = None
    mysql_database: Optional[str] = None
    mysql_charset: Optional[str] = "utf8mb4"

    # Presets
    preset_mcp_config: str = "mcp_setting.json"
    preset_running_config: str = "agent_setting.json"

    # LLM defaults
    default_llm_api_key: Optional[str] = None
    default_llm_api_base_url: Optional[str] = None
    default_llm_model_name: Optional[str] = None
    default_llm_max_tokens: int = 4096
    default_llm_temperature: float = 0.2
    default_llm_max_model_len: int = 54000

    jwt_key: str = "123"
    jwt_expire_hours: int = 24
    refresh_token_secret: str = "123"

    # Embedding
    embed_api_key: Optional[str] = None
    embed_base_url: Optional[str] = None
    embed_model: Optional[str] = None
    embed_dims: int = 1024

    # Elasticsearch
    es_url: Optional[str] = None
    es_api_key: Optional[str] = None
    es_username: Optional[str] = None
    es_password: Optional[str] = None

    # MinIO
    minio_endpoint: Optional[str] = None
    minio_access_key: Optional[str] = None
    minio_secret_key: Optional[str] = None
    minio_secure: bool = False
    minio_bucket_name: Optional[str] = None
    minio_public_base_url: Optional[str] = None


class ENV:
    # 新版 LLM 相关
    DEFAULT_LLM_API_KEY = "SAGE_DEFAULT_LLM_API_KEY"
    DEFAULT_LLM_API_BASE_URL = "SAGE_DEFAULT_LLM_API_BASE_URL"
    DEFAULT_LLM_MODEL_NAME = "SAGE_DEFAULT_LLM_MODEL_NAME"
    DEFAULT_LLM_MAX_TOKENS = "SAGE_DEFAULT_LLM_MAX_TOKENS"
    DEFAULT_LLM_TEMPERATURE = "SAGE_DEFAULT_LLM_TEMPERATURE"
    DEFAULT_LLM_MAX_MODEL_LEN = "SAGE_DEFAULT_LLM_MAX_MODEL_LEN"

    # 服务器与运行配置
    PORT = "SAGE_PORT"
    PRESET_MCP_CONFIG = "SAGE_MCP_CONFIG_PATH"
    PRESET_RUNNING_CONFIG = "SAGE_PRESET_RUNNING_CONFIG_PATH"
    WORKSPACE = "SAGE_WORKSPACE_PATH"
    LOGS_DIR = "SAGE_LOGS_DIR_PATH"
    MEMORY_ROOT = "SAGE_MEMORY_ROOT"
    DAEMON = "SAGE_DAEMON"
    PID_FILE = "SAGE_PID_FILE"
    FORCE_SUMMARY = "SAGE_FORCE_SUMMARY"

    # 数据库
    DB_TYPE = "SAGE_DB_TYPE"
    DB_PATH = "SAGE_DB_PATH"

    # 旧版 LLM 环境变量兜底
    LEGACY_LLM_API_KEY = "LLM_API_KEY"
    LEGACY_LLM_API_BASE_URL = "LLM_API_BASE_URL"
    LEGACY_LLM_MODEL_NAME = "LLM_MODEL_NAME"

    # MinIO
    MINIO_ENDPOINT = "SAGE_MINIO_ENDPOINT"
    MINIO_ACCESS_KEY = "SAGE_MINIO_ACCESS_KEY"
    MINIO_SECRET_KEY = "SAGE_MINIO_SECRET_KEY"
    MINIO_SECURE = "SAGE_MINIO_SECURE"
    MINIO_BUCKET_NAME = "SAGE_MINIO_BUCKET_NAME"
    MINIO_PUBLIC_BASE_URL = "SAGE_MINIO_PUBLIC_BASE_URL"

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


def create_argument_parser():
    """创建命令行参数解析器，支持环境变量，优先级：指定入参 > 环境变量 > 默认值"""
    parser = argparse.ArgumentParser(description="Sage Stream Service")

    # 新格式参数（推荐使用）
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

    # 兼容旧格式（不提供默认值，仍可从 apply_llm_backward_compat 兜底）
    parser.add_argument(
        "--llm_api_key", help=f"LLM API Key（已废弃，请使用--default_llm_api_key）"
    )
    parser.add_argument(
        "--llm_api_base_url",
        help=f"LLM API Base（已废弃，请使用--default_llm_api_base_url）",
    )
    parser.add_argument(
        "--llm_model_name",
        help=f"LLM API Model（已废弃，请使用--default_llm_model_name）",
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
    parser.add_argument(
        "--memory_root",
        help=f"记忆存储根目录（可选） (环境变量: {ENV.MEMORY_ROOT})",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help=f"以守护进程模式运行 (环境变量: {ENV.DAEMON})",
    )
    parser.add_argument(
        "--pid-file",
        help=f"PID文件路径 (环境变量: {ENV.PID_FILE})",
    )
    parser.add_argument(
        "--force_summary",
        action="store_true",
        help=f"是否强制总结 (环境变量: {ENV.FORCE_SUMMARY})",
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

    # MinIO 配置
    parser.add_argument(
        "--minio_endpoint",
        help=f"MinIO Endpoint (环境变量: {ENV.MINIO_ENDPOINT})",
    )
    parser.add_argument(
        "--minio_access_key",
        help=f"MinIO Access Key (环境变量: {ENV.MINIO_ACCESS_KEY})",
    )
    parser.add_argument(
        "--minio_secret_key",
        help=f"MinIO Secret Key (环境变量: {ENV.MINIO_SECRET_KEY})",
    )
    parser.add_argument(
        "--minio_secure",
        action="store_true",
        help=f"MinIO 使用 https (环境变量: {ENV.MINIO_SECURE})",
    )
    parser.add_argument(
        "--minio_bucket_name",
        help=f"MinIO Bucket (环境变量: {ENV.MINIO_BUCKET_NAME})",
    )
    parser.add_argument(
        "--minio_public_base_url",
        help=f"MinIO Public Base URL (环境变量: {ENV.MINIO_PUBLIC_BASE_URL})",
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


def apply_llm_backward_compat(
    cfg: StartupConfig, args: argparse.Namespace
) -> StartupConfig:
    """处理LLM参数向后兼容：直接使用解析器值，仅在缺失时兜底旧环境变量"""
    api_key = args.default_llm_api_key or env_str(ENV.DEFAULT_LLM_API_KEY)
    base_url = args.default_llm_api_base_url or env_str(ENV.DEFAULT_LLM_API_BASE_URL)
    model_name = args.default_llm_model_name or env_str(ENV.DEFAULT_LLM_MODEL_NAME)
    max_tokens = (
        args.default_llm_max_tokens
        if args.default_llm_max_tokens is not None
        else env_int(ENV.DEFAULT_LLM_MAX_TOKENS, 4096)
    )
    temperature = (
        args.default_llm_temperature
        if args.default_llm_temperature is not None
        else env_float(ENV.DEFAULT_LLM_TEMPERATURE, 0.2)
    )
    max_model_len = (
        args.default_llm_max_model_len
        if args.default_llm_max_model_len is not None
        else env_int(ENV.DEFAULT_LLM_MAX_MODEL_LEN, 54000)
    )

    # 旧参数兜底（仅在新参数未提供时）
    api_key = api_key or args.llm_api_key or env_str(ENV.LEGACY_LLM_API_KEY)
    base_url = base_url or args.llm_api_base_url or env_str(ENV.LEGACY_LLM_API_BASE_URL)
    model_name = model_name or args.llm_model_name or env_str(ENV.LEGACY_LLM_MODEL_NAME)

    if max_model_len is None or max_model_len < 8000:
        max_model_len = 54000

    cfg.default_llm_api_key = api_key
    cfg.default_llm_api_base_url = base_url
    cfg.default_llm_model_name = model_name
    cfg.default_llm_max_tokens = max_tokens or cfg.default_llm_max_tokens
    cfg.default_llm_temperature = temperature or cfg.default_llm_temperature
    cfg.default_llm_max_model_len = max_model_len
    return cfg


def build_startup_config() -> StartupConfig:
    """解析命令行并按优先级合并环境变量与默认值，得到结构化启动配置"""
    parser = create_argument_parser()
    args = parser.parse_args()

    cfg = StartupConfig(
        port=pick_int(args.port, ENV.PORT, 8001),
        daemon=pick_bool(args.daemon, ENV.DAEMON, False),
        pid_file=pick_str(args.pid_file, ENV.PID_FILE, "sage_stream.pid"),
        logs_dir=pick_str(args.logs_dir, ENV.LOGS_DIR, "logs"),
        workspace=pick_str(args.workspace, ENV.WORKSPACE, "agent_workspace"),
        memory_root=pick_str(args.memory_root, ENV.MEMORY_ROOT),
        force_summary=pick_bool(args.force_summary, ENV.FORCE_SUMMARY, False),
        db_type=pick_str(args.db_type, ENV.DB_TYPE, "file"),
        db_path=pick_str(args.db_path, ENV.DB_PATH, "./data/"),
        mysql_host=pick_str(args.mysql_host, ENV.MYSQL_HOST, "127.0.0.1"),
        mysql_port=pick_int(args.mysql_port, ENV.MYSQL_PORT, 3306),
        mysql_user=pick_str(args.mysql_user, ENV.MYSQL_USER, "root"),
        mysql_password=pick_str(args.mysql_password, ENV.MYSQL_PASSWORD, "sage.1234"),
        mysql_database=pick_str(args.mysql_database, ENV.MYSQL_DATABASE, "sage"),
        mysql_charset="utf8mb4",
        preset_mcp_config=pick_str(
            args.preset_mcp_config, ENV.PRESET_MCP_CONFIG, "mcp_setting.json"
        ),
        preset_running_config=pick_str(
            args.preset_running_config, ENV.PRESET_RUNNING_CONFIG, "agent_setting.json"
        ),
        embed_api_key=pick_str(args.embedding_api_key, ENV.EMBEDDING_API_KEY),
        embed_base_url=pick_str(args.embedding_base_url, ENV.EMBEDDING_BASE_URL),
        embed_model=pick_str(
            args.embedding_model, ENV.EMBEDDING_MODEL, "text-embedding-3-large"
        ),
        embed_dims=pick_int(args.embedding_dims, ENV.EMBEDDING_DIMS, 1024),
        es_url=pick_str(args.es_url, ENV.ES_URL),
        es_api_key=pick_str(args.es_api_key, ENV.ES_API_KEY),
        es_username=pick_str(args.es_username, ENV.ES_USERNAME),
        es_password=pick_str(args.es_password, ENV.ES_PASSWORD),
        minio_endpoint=pick_str(args.minio_endpoint, ENV.MINIO_ENDPOINT),
        minio_access_key=pick_str(args.minio_access_key, ENV.MINIO_ACCESS_KEY),
        minio_secret_key=pick_str(args.minio_secret_key, ENV.MINIO_SECRET_KEY),
        minio_secure=pick_bool(args.minio_secure, ENV.MINIO_SECURE, False),
        minio_bucket_name=pick_str(args.minio_bucket_name, ENV.MINIO_BUCKET_NAME),
        minio_public_base_url=pick_str(
            args.minio_public_base_url, ENV.MINIO_PUBLIC_BASE_URL
        ),
    )

    # 处理 LLM 兼容性和默认值
    cfg = apply_llm_backward_compat(cfg, args)

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


def init_startup_config():
    global _GLOBAL_STARTUP_CONFIG
    cfg = build_startup_config()
    _GLOBAL_STARTUP_CONFIG = cfg
