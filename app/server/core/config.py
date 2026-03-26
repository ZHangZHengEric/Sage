"""
配置相关, 支持环境变量、默认值
"""

import os
from dataclasses import dataclass
from typing import Any, Optional

# ===== 全局启动参数（统一存放于此） =====
_GLOBAL_STARTUP_CONFIG: Optional[Any] = None


@dataclass
class StartupConfig:
    """启动参数结构体，优先级：环境变量 > 默认值"""

    # Server
    port: int = 8080
    logs_dir: str = "logs"
    session_dir: str = "sessions"
    agents_dir: str = "agents"
    skill_dir: str = "skills"  # 技能根目录（系统技能）
    user_dir: str = "users"  # 用户目录根路径
    # DB
    db_type: str = "file"  # file | memory | mysql
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "sage.1234"
    mysql_database: str = "sage"
    mysql_charset: str = "utf8mb4"

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
    auth_providers_json: Optional[str] = None
    jwt_key: str = "sage_dev_jwt_secret_key_change_me_in_prod_v1"
    jwt_expire_hours: int = 24
    refresh_token_secret: str = "sage_dev_refresh_secret_key_change_me_in_prod_v1"
    session_secret: str = "sage_dev_session_secret_key_change_me_in_prod_v1"
    session_cookie_name: str = "sage_session"
    session_cookie_secure: bool = False
    session_cookie_same_site: str = "lax"
    web_base_path: str = "/sage"

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
    trace_jaeger_ui_url: str = "http://127.0.0.1:30051/jaeger"
    trace_jaeger_public_url: str = "http://127.0.0.1:30051/jaeger"
    trace_jaeger_base_path: str = "/api/observability/jaeger"


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
    TRACE_JAEGER_ENDPOINT = "SAGE_TRACE_JAEGER_ENDPOINT"
    TRACE_JAEGER_UI_URL = "SAGE_TRACE_JAEGER_UI_URL"
    TRACE_JAEGER_PUBLIC_URL = "SAGE_TRACE_JAEGER_PUBLIC_URL"
    TRACE_JAEGER_BASE_PATH = "SAGE_TRACE_JAEGER_BASE_PATH"

    # 服务器与运行配置
    PORT = "SAGE_PORT"
    SESSION_DIR = "SAGE_SESSION_DIR"
    LOGS_DIR = "SAGE_LOGS_DIR_PATH"
    AGENTS_DIR = "SAGE_AGENTS_DIR"
    USER_DIR = "SAGE_USER_DIR"
    # 数据库
    DB_TYPE = "SAGE_DB_TYPE"

    # S3
    S3_ENDPOINT = "SAGE_S3_ENDPOINT"
    S3_ACCESS_KEY = "SAGE_S3_ACCESS_KEY"
    S3_SECRET_KEY = "SAGE_S3_SECRET_KEY"
    S3_SECURE = "SAGE_S3_SECURE"
    S3_BUCKET_NAME = "SAGE_S3_BUCKET_NAME"
    S3_PUBLIC_BASE_URL = "SAGE_S3_PUBLIC_BASE_URL"

    # Skill Workspace
    SKILL_DIR = "SAGE_SKILL_WORKSPACE"

    # Knowledge Base MCP 接口
    KB_MCP_URL = "SAGE_KB_MCP_URL"
    KB_MCP_API_KEY = "SAGE_KB_MCP_API_KEY"

    AUTH_PROVIDERS = "SAGE_AUTH_PROVIDERS"
    JWT_KEY = "SAGE_JWT_KEY"
    JWT_EXPIRE_HOURS = "SAGE_JWT_EXPIRE_HOURS"
    REFRESH_TOKEN_SECRET = "SAGE_REFRESH_TOKEN_SECRET"
    SESSION_SECRET = "SAGE_SESSION_SECRET"
    SESSION_COOKIE_NAME = "SAGE_SESSION_COOKIE_NAME"
    SESSION_COOKIE_SECURE = "SAGE_SESSION_COOKIE_SECURE"
    SESSION_COOKIE_SAME_SITE = "SAGE_SESSION_COOKIE_SAME_SITE"
    WEB_BASE_PATH = "SAGE_WEB_BASE_PATH"
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


def build_startup_config() -> StartupConfig:
    """解析环境变量与默认值，得到结构化启动配置"""

    cfg = StartupConfig(
        port=env_int(ENV.PORT, StartupConfig.port),
        logs_dir=env_str(ENV.LOGS_DIR, StartupConfig.logs_dir),
        session_dir=env_str(ENV.SESSION_DIR, StartupConfig.session_dir),
        agents_dir=env_str(ENV.AGENTS_DIR, StartupConfig.agents_dir),
        skill_dir=env_str(ENV.SKILL_DIR, StartupConfig.skill_dir),
        user_dir=env_str(ENV.USER_DIR, StartupConfig.user_dir),

        db_type=env_str(ENV.DB_TYPE, StartupConfig.db_type),
        mysql_host=env_str(ENV.MYSQL_HOST, StartupConfig.mysql_host),
        mysql_port=env_int(ENV.MYSQL_PORT, StartupConfig.mysql_port),
        mysql_user=env_str(ENV.MYSQL_USER, StartupConfig.mysql_user),
        mysql_password=env_str(
            ENV.MYSQL_PASSWORD, StartupConfig.mysql_password
        ),
        mysql_database=env_str(
            ENV.MYSQL_DATABASE, StartupConfig.mysql_database
        ),
        mysql_charset=StartupConfig.mysql_charset,

        default_llm_api_key=env_str(
            ENV.DEFAULT_LLM_API_KEY,
            StartupConfig.default_llm_api_key,
        ),
        default_llm_api_base_url=env_str(
            ENV.DEFAULT_LLM_API_BASE_URL,
            StartupConfig.default_llm_api_base_url,
        ),
        default_llm_model_name=env_str(
            ENV.DEFAULT_LLM_MODEL_NAME,
            StartupConfig.default_llm_model_name,
        ),
        default_llm_max_tokens=env_int(
            ENV.DEFAULT_LLM_MAX_TOKENS,
            StartupConfig.default_llm_max_tokens,
        ),
        default_llm_temperature=env_float(
            ENV.DEFAULT_LLM_TEMPERATURE,
            StartupConfig.default_llm_temperature,
        ),
        default_llm_max_model_len=env_int(
            ENV.DEFAULT_LLM_MAX_MODEL_LEN,
            StartupConfig.default_llm_max_model_len,
        ),
        default_llm_top_p=env_float(
            ENV.DEFAULT_LLM_TOP_P,
            StartupConfig.default_llm_top_p,
        ),
        default_llm_presence_penalty=env_float(
            ENV.DEFAULT_LLM_PRESENCE_PENALTY,
            StartupConfig.default_llm_presence_penalty,
        ),
        context_history_ratio=env_float(
            ENV.CONTEXT_HISTORY_RATIO,
            StartupConfig.context_history_ratio,
        ),
        context_active_ratio=env_float(
            ENV.CONTEXT_ACTIVE_RATIO,
            StartupConfig.context_active_ratio,
        ),
        context_max_new_message_ratio=env_float(
            ENV.CONTEXT_MAX_NEW_MESSAGE_RATIO,
            StartupConfig.context_max_new_message_ratio,
        ),
        context_recent_turns=env_int(
            ENV.CONTEXT_RECENT_TURNS,
            StartupConfig.context_recent_turns,
        ),
        auth_providers_json=env_str(
            ENV.AUTH_PROVIDERS,
            StartupConfig.auth_providers_json,
        ),
        jwt_key=env_str(ENV.JWT_KEY, StartupConfig.jwt_key),
        jwt_expire_hours=env_int(
            ENV.JWT_EXPIRE_HOURS, StartupConfig.jwt_expire_hours
        ),
        refresh_token_secret=env_str(
            ENV.REFRESH_TOKEN_SECRET,
            StartupConfig.refresh_token_secret,
        ),
        session_secret=env_str(
            ENV.SESSION_SECRET,
            StartupConfig.session_secret,
        ),
        session_cookie_name=env_str(
            ENV.SESSION_COOKIE_NAME,
            StartupConfig.session_cookie_name,
        ),
        session_cookie_secure=env_bool(
            ENV.SESSION_COOKIE_SECURE,
            StartupConfig.session_cookie_secure,
        ),
        session_cookie_same_site=(env_str(
            ENV.SESSION_COOKIE_SAME_SITE,
            StartupConfig.session_cookie_same_site,
        ) or StartupConfig.session_cookie_same_site).strip().lower(),
        web_base_path=env_str(
            ENV.WEB_BASE_PATH,
            StartupConfig.web_base_path,
        ),
        embed_api_key=env_str(
            ENV.EMBEDDING_API_KEY, StartupConfig.embed_api_key
        ),
        embed_base_url=env_str(
            ENV.EMBEDDING_BASE_URL,
            StartupConfig.embed_base_url,
        ),
        embed_model=env_str(
            ENV.EMBEDDING_MODEL, StartupConfig.embed_model
        ),
        embed_dims=env_int(
            ENV.EMBEDDING_DIMS, StartupConfig.embed_dims
        ),
        es_url=env_str(ENV.ES_URL, StartupConfig.es_url),
        es_api_key=env_str(ENV.ES_API_KEY, StartupConfig.es_api_key),
        es_username=env_str(
            ENV.ES_USERNAME, StartupConfig.es_username
        ),
        es_password=env_str(
            ENV.ES_PASSWORD, StartupConfig.es_password
        ),
        s3_endpoint=env_str(
            ENV.S3_ENDPOINT, StartupConfig.s3_endpoint
        ),
        s3_access_key=env_str(
            ENV.S3_ACCESS_KEY, StartupConfig.s3_access_key
        ),
        s3_secret_key=env_str(
            ENV.S3_SECRET_KEY, StartupConfig.s3_secret_key
        ),
        s3_secure=env_bool(
            ENV.S3_SECURE, StartupConfig.s3_secure
        ),
        s3_bucket_name=env_str(
            ENV.S3_BUCKET_NAME,
            StartupConfig.s3_bucket_name,
        ),
        s3_public_base_url=env_str(
            ENV.S3_PUBLIC_BASE_URL,
            StartupConfig.s3_public_base_url,
        ),
        trace_jaeger_endpoint=env_str(
            ENV.TRACE_JAEGER_URL,
            env_str(
                ENV.TRACE_JAEGER_ENDPOINT,
                StartupConfig.trace_jaeger_endpoint,
            ),
        ),
        trace_jaeger_ui_url=env_str(
            ENV.TRACE_JAEGER_UI_URL,
            StartupConfig.trace_jaeger_ui_url,
        ),
        trace_jaeger_public_url=env_str(
            ENV.TRACE_JAEGER_PUBLIC_URL,
            StartupConfig.trace_jaeger_public_url,
        ),
        trace_jaeger_base_path=env_str(
            ENV.TRACE_JAEGER_BASE_PATH,
            StartupConfig.trace_jaeger_base_path,
        ),
    )
    cfg.session_cookie_same_site = (
        (cfg.session_cookie_same_site or StartupConfig.session_cookie_same_site)
        .strip()
        .lower()
    )
    if cfg.session_cookie_same_site not in {"lax", "strict", "none"}:
        cfg.session_cookie_same_site = StartupConfig.session_cookie_same_site
    if cfg.web_base_path:
        cfg.web_base_path = "/" + cfg.web_base_path.strip("/")
    else:
        cfg.web_base_path = StartupConfig.web_base_path
    if cfg.trace_jaeger_base_path:
        cfg.trace_jaeger_base_path = "/" + cfg.trace_jaeger_base_path.strip("/")

    # 规范化路径
    if cfg.session_dir:
        cfg.session_dir = os.path.abspath(cfg.session_dir)
        os.makedirs(cfg.session_dir, exist_ok=True)
    if cfg.logs_dir:
        cfg.logs_dir = os.path.abspath(cfg.logs_dir)
        os.makedirs(cfg.logs_dir, exist_ok=True)
    if cfg.agents_dir:
        cfg.agents_dir = os.path.abspath(cfg.agents_dir)
        os.makedirs(cfg.agents_dir, exist_ok=True)
    if cfg.skill_dir:
        cfg.skill_dir = os.path.abspath(cfg.skill_dir)
        os.makedirs(cfg.skill_dir, exist_ok=True)
    if cfg.user_dir:
        cfg.user_dir = os.path.abspath(cfg.user_dir)
        os.makedirs(cfg.user_dir, exist_ok=True)

    return cfg


def get_startup_config() -> StartupConfig:
    return _GLOBAL_STARTUP_CONFIG


def init_startup_config() -> StartupConfig:
    global _GLOBAL_STARTUP_CONFIG
    cfg = build_startup_config()
    _GLOBAL_STARTUP_CONFIG = cfg
    return cfg
