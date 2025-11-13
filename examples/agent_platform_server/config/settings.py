"""
配置相关, 支持命令行参数、环境变量、默认值
"""

import os
import argparse
from dataclasses import dataclass
from typing import Optional


@dataclass
class StartupConfig:
    """启动参数结构体，优先级：命令行 > 环境变量 > 默认值"""

    # Server
    host: str = "0.0.0.0"
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


class ENV:
    # 新版 LLM 相关
    DEFAULT_LLM_API_KEY = "SAGE_DEFAULT_LLM_API_KEY"
    DEFAULT_LLM_API_BASE_URL = "SAGE_DEFAULT_LLM_API_BASE_URL"
    DEFAULT_LLM_MODEL_NAME = "SAGE_DEFAULT_LLM_MODEL_NAME"
    DEFAULT_LLM_MAX_TOKENS = "SAGE_DEFAULT_LLM_MAX_TOKENS"
    DEFAULT_LLM_TEMPERATURE = "SAGE_DEFAULT_LLM_TEMPERATURE"
    DEFAULT_LLM_MAX_MODEL_LEN = "SAGE_DEFAULT_LLM_MAX_MODEL_LEN"

    # 服务器与运行配置
    HOST = "SAGE_HOST"
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


def create_argument_parser():
    """创建命令行参数解析器，支持环境变量，优先级：指定入参 > 环境变量 > 默认值"""
    parser = argparse.ArgumentParser(description="Sage Stream Service")

    # 新格式参数（推荐使用）
    parser.add_argument(
        "--default_llm_api_key",
        default=env_str(ENV.DEFAULT_LLM_API_KEY),
        help=f"默认LLM API Key (环境变量: {ENV.DEFAULT_LLM_API_KEY})",
    )
    parser.add_argument(
        "--default_llm_api_base_url",
        default=env_str(ENV.DEFAULT_LLM_API_BASE_URL),
        help=f"默认LLM API Base (环境变量: {ENV.DEFAULT_LLM_API_BASE_URL})",
    )
    parser.add_argument(
        "--default_llm_model_name",
        default=env_str(ENV.DEFAULT_LLM_MODEL_NAME),
        help=f"默认LLM API Model (环境变量: {ENV.DEFAULT_LLM_MODEL_NAME})",
    )
    parser.add_argument(
        "--default_llm_max_tokens",
        default=env_int(ENV.DEFAULT_LLM_MAX_TOKENS, 4096),
        type=int,
        help=f"默认LLM API Max Tokens (环境变量: {ENV.DEFAULT_LLM_MAX_TOKENS})",
    )
    parser.add_argument(
        "--default_llm_temperature",
        default=env_float(ENV.DEFAULT_LLM_TEMPERATURE, 0.2),
        type=float,
        help=f"默认LLM API Temperature (环境变量: {ENV.DEFAULT_LLM_TEMPERATURE})",
    )
    parser.add_argument(
        "--default_llm_max_model_len",
        default=env_int(ENV.DEFAULT_LLM_MAX_MODEL_LEN, 54000),
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

    # Server
    parser.add_argument(
        "--host",
        default=env_str(ENV.HOST, "0.0.0.0"),
        help=f"Server Host (环境变量: {ENV.HOST})",
    )
    parser.add_argument(
        "--port",
        default=env_int(ENV.PORT, 8001),
        type=int,
        help=f"Server Port (环境变量: {ENV.PORT})",
    )
    parser.add_argument(
        "--preset_mcp_config",
        default=env_str(ENV.PRESET_MCP_CONFIG, "mcp_setting.json"),
        help=f"MCP配置文件路径 (环境变量: {ENV.PRESET_MCP_CONFIG})",
    )
    parser.add_argument(
        "--preset_running_config",
        default=env_str(ENV.PRESET_RUNNING_CONFIG, "agent_setting.json"),
        help=f"预设配置，system_context，以及workflow，与接口中传过来的合并使用 (环境变量: {ENV.PRESET_RUNNING_CONFIG})",
    )
    parser.add_argument(
        "--workspace",
        default=env_str(ENV.WORKSPACE, "agent_workspace"),
        help=f"工作空间目录 (环境变量: {ENV.WORKSPACE})",
    )
    parser.add_argument(
        "--logs-dir",
        default=env_str(ENV.LOGS_DIR, "logs"),
        help=f"日志目录 (环境变量: {ENV.LOGS_DIR})",
    )
    parser.add_argument(
        "--memory_root",
        default=env_str(ENV.MEMORY_ROOT),
        help=f"记忆存储根目录（可选） (环境变量: {ENV.MEMORY_ROOT})",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        default=env_bool(ENV.DAEMON, False),
        help=f"以守护进程模式运行 (环境变量: {ENV.DAEMON})",
    )
    parser.add_argument(
        "--pid-file",
        default=env_str(ENV.PID_FILE, "sage_stream.pid"),
        help=f"PID文件路径 (环境变量: {ENV.PID_FILE})",
    )
    parser.add_argument(
        "--force_summary",
        action="store_true",
        default=env_bool(ENV.FORCE_SUMMARY, False),
        help=f"是否强制总结 (环境变量: {ENV.FORCE_SUMMARY})",
    )

    # 数据库相关参数
    parser.add_argument(
        "--db_type",
        default=env_str(ENV.DB_TYPE, "file"),
        choices=["file", "memory"],
        help=f"数据库类型：file（文件模式）或memory（内存模式） (环境变量: {ENV.DB_TYPE})",
    )
    parser.add_argument(
        "--db_path",
        default=env_str(ENV.DB_PATH, "./data/"),
        help=f"数据库文件存储路径，仅在file模式下有效 (环境变量: {ENV.DB_PATH})",
    )

    return parser


def apply_llm_backward_compat(
    cfg: StartupConfig, args: argparse.Namespace
) -> StartupConfig:
    """处理LLM参数向后兼容：直接使用解析器值，仅在缺失时兜底旧环境变量"""
    # 新参数（解析器已提供环境默认值）
    api_key = args.default_llm_api_key
    base_url = args.default_llm_api_base_url
    model_name = args.default_llm_model_name
    max_tokens = args.default_llm_max_tokens
    temperature = args.default_llm_temperature
    max_model_len = args.default_llm_max_model_len

    # 旧参数兜底（仅在新参数未提供时）
    api_key = api_key or args.llm_api_key or env_str(ENV.LEGACY_LLM_API_KEY)
    base_url = base_url or args.llm_api_base_url or env_str(ENV.LEGACY_LLM_API_BASE_URL)
    model_name = model_name or args.llm_model_name or env_str(ENV.LEGACY_LLM_MODEL_NAME)

    # 校正 max_model_len
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

    # 基础配置：解析器已合并环境默认值，此处直接使用解析器值
    cfg = StartupConfig(
        host=args.host,
        port=args.port,
        daemon=bool(args.daemon),
        pid_file=args.pid_file,
        logs_dir=args.logs_dir,
        workspace=args.workspace,
        memory_root=args.memory_root,
        force_summary=bool(args.force_summary),
        db_type=args.db_type,
        db_path=args.db_path,
        preset_mcp_config=args.preset_mcp_config,
        preset_running_config=args.preset_running_config,
    )

    # 处理 LLM 兼容性和默认值
    cfg = apply_llm_backward_compat(cfg, args)

    # 规范化路径
    if cfg.workspace:
        cfg.workspace = os.path.abspath(cfg.workspace)
    if cfg.logs_dir:
        cfg.logs_dir = os.path.abspath(cfg.logs_dir)
    if cfg.db_type == "file" and cfg.db_path:
        cfg.db_path = os.path.abspath(cfg.db_path)
    return cfg
