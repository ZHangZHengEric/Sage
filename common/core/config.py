"""
共享配置模块，供 server / desktop 共用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_GLOBAL_STARTUP_CONFIG: Any


def get_default_sage_home() -> Path:
    return Path.home() / ".sage"


def get_local_storage_defaults() -> Dict[str, str]:
    sage_home = get_default_sage_home()
    return {
        "sage_home": str(sage_home),
        "logs_dir": str(sage_home / "logs"),
        "session_dir": str(sage_home / "sessions"),
        "agents_dir": str(sage_home / "agents"),
        "skill_dir": str(sage_home / "skills"),
        "user_dir": str(sage_home / "users"),
        "db_file": str(sage_home / "sage.db"),
        "env_file": str(sage_home / ".sage_env"),
    }


@dataclass
class StartupConfig:
    app_mode: str = "server"

    env: str = "development"
    auth_mode: str = "native"
    port: int = 8080
    logs_dir: str = "logs"
    session_dir: str = "sessions"
    agents_dir: str = "agents"
    skill_dir: str = "skills"
    user_dir: str = "users"
    workspace: str = "agent_workspace"

    db_type: str = "file"
    db_file: str = "./sage.db"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "sage.1234"
    mysql_database: str = "sage"
    mysql_charset: str = "utf8mb4"

    preset_mcp_config: str = "mcp_setting.json"
    preset_running_config: str = "agent_setting.json"

    default_llm_api_key: str = ""
    default_llm_api_base_url: str = "https://api.deepseek.com/v1"
    default_llm_model_name: str = "deepseek-chat"
    default_llm_max_tokens: int = 4096
    default_llm_temperature: float = 0.2
    default_llm_max_model_len: int = 54000
    default_llm_top_p: float = 0.9
    default_llm_presence_penalty: float = 0.0

    context_history_ratio: float = 0.2
    context_active_ratio: float = 0.3
    context_max_new_message_ratio: float = 0.5
    context_recent_turns: int = 0

    auth_providers_json: Optional[str] = None
    trusted_identity_proxy_ips: list[str] | None = None
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""
    jwt_key: str = "sage_dev_jwt_secret_key_change_me_in_prod_v1"
    jwt_expire_hours: int = 24
    refresh_token_secret: str = "sage_dev_refresh_secret_key_change_me_in_prod_v1"
    session_secret: str = "sage_dev_session_secret_key_change_me_in_prod_v1"
    session_cookie_name: str = "sage_session"
    session_cookie_secure: bool = False
    session_cookie_same_site: str = "lax"
    cors_allowed_origins: list[str] = field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = field(default_factory=lambda: ["*"])
    cors_expose_headers: list[str] = field(default_factory=list)
    cors_max_age: int = 600
    web_base_path: str = "/sage"
    oauth2_clients_json: Optional[str] = None
    oauth2_issuer: Optional[str] = None
    oauth2_access_token_expires_in: int = 3600
    eml_endpoint: str = "dm.aliyuncs.com"
    eml_access_key_id: Optional[str] = None
    eml_access_key_secret: Optional[str] = None
    eml_security_token: Optional[str] = None
    eml_account_name: Optional[str] = None
    eml_template_id: Optional[str] = None
    eml_register_subject: str = ""
    eml_address_type: int = 1
    eml_reply_to_address: bool = False

    embed_api_key: Optional[str] = None
    embed_base_url: Optional[str] = None
    embed_model: str = "text-embedding-3-large"
    embed_dims: int = 1024

    es_url: Optional[str] = None
    es_api_key: Optional[str] = None
    es_username: Optional[str] = None
    es_password: Optional[str] = None

    s3_endpoint: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_secure: bool = False
    s3_bucket_name: Optional[str] = None
    s3_public_base_url: Optional[str] = None

    trace_jaeger_endpoint: Optional[str] = None
    trace_jaeger_public_url: Optional[str] = "http://127.0.0.1:30051/jaeger"


class ENV:
    APP_ENV = "SAGE_ENV"
    AUTH_MODE = "SAGE_AUTH_MODE"

    DEFAULT_LLM_API_KEY = "SAGE_DEFAULT_LLM_API_KEY"
    DEFAULT_LLM_API_BASE_URL = "SAGE_DEFAULT_LLM_API_BASE_URL"
    DEFAULT_LLM_MODEL_NAME = "SAGE_DEFAULT_LLM_MODEL_NAME"
    DEFAULT_LLM_MAX_TOKENS = "SAGE_DEFAULT_LLM_MAX_TOKENS"
    DEFAULT_LLM_TEMPERATURE = "SAGE_DEFAULT_LLM_TEMPERATURE"
    DEFAULT_LLM_MAX_MODEL_LEN = "SAGE_DEFAULT_LLM_MAX_MODEL_LEN"
    DEFAULT_LLM_TOP_P = "SAGE_DEFAULT_LLM_TOP_P"
    DEFAULT_LLM_PRESENCE_PENALTY = "SAGE_DEFAULT_LLM_PRESENCE_PENALTY"

    CONTEXT_HISTORY_RATIO = "SAGE_CONTEXT_HISTORY_RATIO"
    CONTEXT_ACTIVE_RATIO = "SAGE_CONTEXT_ACTIVE_RATIO"
    CONTEXT_MAX_NEW_MESSAGE_RATIO = "SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO"
    CONTEXT_RECENT_TURNS = "SAGE_CONTEXT_RECENT_TURNS"

    TRACE_JAEGER_URL = "SAGE_TRACE_JAEGER_URL"
    TRACE_JAEGER_ENDPOINT = "SAGE_TRACE_JAEGER_ENDPOINT"
    TRACE_JAEGER_UI_URL = "SAGE_TRACE_JAEGER_UI_URL"
    TRACE_JAEGER_PUBLIC_URL = "SAGE_TRACE_JAEGER_PUBLIC_URL"
    TRACE_JAEGER_BASE_PATH = "SAGE_TRACE_JAEGER_BASE_PATH"

    PORT = "SAGE_PORT"
    SESSION_DIR = "SAGE_SESSION_DIR"
    LOGS_DIR = "SAGE_LOGS_DIR_PATH"
    AGENTS_DIR = "SAGE_AGENTS_DIR"
    USER_DIR = "SAGE_USER_DIR"
    DB_TYPE = "SAGE_DB_TYPE"
    DB_FILE = "SAGE_DB_FILE"

    S3_ENDPOINT = "SAGE_S3_ENDPOINT"
    S3_ACCESS_KEY = "SAGE_S3_ACCESS_KEY"
    S3_SECRET_KEY = "SAGE_S3_SECRET_KEY"
    S3_SECURE = "SAGE_S3_SECURE"
    S3_BUCKET_NAME = "SAGE_S3_BUCKET_NAME"
    S3_PUBLIC_BASE_URL = "SAGE_S3_PUBLIC_BASE_URL"

    SKILL_DIR = "SAGE_SKILL_WORKSPACE"
    KB_MCP_URL = "SAGE_KB_MCP_URL"
    KB_MCP_API_KEY = "SAGE_KB_MCP_API_KEY"

    AUTH_PROVIDERS = "SAGE_AUTH_PROVIDERS"
    TRUSTED_IDENTITY_PROXY_IPS = "SAGE_TRUSTED_IDENTITY_PROXY_IPS"
    BOOTSTRAP_ADMIN_USERNAME = "SAGE_BOOTSTRAP_ADMIN_USERNAME"
    BOOTSTRAP_ADMIN_PASSWORD = "SAGE_BOOTSTRAP_ADMIN_PASSWORD"
    JWT_KEY = "SAGE_JWT_KEY"
    JWT_EXPIRE_HOURS = "SAGE_JWT_EXPIRE_HOURS"
    REFRESH_TOKEN_SECRET = "SAGE_REFRESH_TOKEN_SECRET"
    SESSION_SECRET = "SAGE_SESSION_SECRET"
    SESSION_COOKIE_NAME = "SAGE_SESSION_COOKIE_NAME"
    SESSION_COOKIE_SECURE = "SAGE_SESSION_COOKIE_SECURE"
    SESSION_COOKIE_SAME_SITE = "SAGE_SESSION_COOKIE_SAME_SITE"
    CORS_ALLOWED_ORIGINS = "SAGE_CORS_ALLOWED_ORIGINS"
    CORS_ALLOW_CREDENTIALS = "SAGE_CORS_ALLOW_CREDENTIALS"
    CORS_ALLOW_METHODS = "SAGE_CORS_ALLOW_METHODS"
    CORS_ALLOW_HEADERS = "SAGE_CORS_ALLOW_HEADERS"
    CORS_EXPOSE_HEADERS = "SAGE_CORS_EXPOSE_HEADERS"
    CORS_MAX_AGE = "SAGE_CORS_MAX_AGE"
    WEB_BASE_PATH = "SAGE_WEB_BASE_PATH"
    OAUTH2_CLIENTS = "SAGE_OAUTH2_CLIENTS"
    OAUTH2_ISSUER = "SAGE_OAUTH2_ISSUER"
    OAUTH2_ACCESS_TOKEN_EXPIRES_IN = "SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN"
    EML_ENDPOINT = "SAGE_EML_ENDPOINT"
    EML_ACCESS_KEY_ID = "SAGE_EML_ACCESS_KEY_ID"
    EML_ACCESS_KEY_SECRET = "SAGE_EML_ACCESS_KEY_SECRET"
    EML_SECURITY_TOKEN = "SAGE_EML_SECURITY_TOKEN"
    EML_ACCOUNT_NAME = "SAGE_EML_ACCOUNT_NAME"
    EML_TEMPLATE_ID = "SAGE_EML_TEMPLATE_ID"
    EML_REGISTER_SUBJECT = "SAGE_EML_REGISTER_SUBJECT"
    EML_ADDRESS_TYPE = "SAGE_EML_ADDRESS_TYPE"
    EML_REPLY_TO_ADDRESS = "SAGE_EML_REPLY_TO_ADDRESS"
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

    PRESET_MCP_CONFIG = "SAGE_MCP_CONFIG_PATH"
    PRESET_RUNNING_CONFIG = "SAGE_PRESET_RUNNING_CONFIG_PATH"
    LEGACY_LLM_API_KEY = "LLM_API_KEY"
    LEGACY_LLM_API_BASE_URL = "LLM_API_BASE_URL"
    LEGACY_LLM_MODEL_NAME = "LLM_MODEL_NAME"


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


def env_csv(name: str, default: Optional[list[str]] = None) -> list[str]:
    val = os.getenv(name)
    if val is None:
        return list(default or [])
    if not val:
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


def is_production_like(cfg: StartupConfig) -> bool:
    return (cfg.env or "").strip().lower() in {"production", "staging"}


def validate_startup_config(cfg: StartupConfig) -> None:
    if cfg.app_mode != "server":
        return

    auth_mode = (cfg.auth_mode or "").strip().lower()
    if auth_mode not in {"trusted_proxy", "oauth", "native"}:
        raise ValueError("Unsupported auth mode. Expected trusted_proxy, oauth, or native.")

    if not is_production_like(cfg):
        if cfg.cors_allow_credentials and "*" in (cfg.cors_allowed_origins or []):
            raise ValueError("Credentialed wildcard CORS is not allowed.")
        return

    default_secrets = {
        "jwt_key": StartupConfig.jwt_key,
        "refresh_token_secret": StartupConfig.refresh_token_secret,
        "session_secret": StartupConfig.session_secret,
    }
    insecure = [name for name, default in default_secrets.items() if getattr(cfg, name) == default]
    if insecure:
        raise ValueError("Production-like environments must use secure secrets.")

    if not cfg.session_cookie_secure:
        raise ValueError("Production-like environments must enable secure session cookies.")

    if cfg.cors_allow_credentials and "*" in (cfg.cors_allowed_origins or []):
        raise ValueError("Credentialed wildcard CORS is not allowed.")


def _normalize_paths(cfg: StartupConfig) -> StartupConfig:
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
    if cfg.db_type == "file" and cfg.db_file:
        cfg.db_file = os.path.abspath(cfg.db_file)
        os.makedirs(os.path.dirname(cfg.db_file), exist_ok=True)
    return cfg


def build_startup_config(mode: str = "server") -> StartupConfig:
    if mode == "desktop":
        local_defaults = get_local_storage_defaults()
        cfg = StartupConfig(
            app_mode="desktop",
            port=env_int(ENV.PORT, StartupConfig.port),
            logs_dir=env_str(ENV.LOGS_DIR, local_defaults["logs_dir"]) or local_defaults["logs_dir"],
            session_dir=env_str(ENV.SESSION_DIR, local_defaults["session_dir"]) or local_defaults["session_dir"],
            agents_dir=env_str(ENV.AGENTS_DIR, local_defaults["agents_dir"]) or local_defaults["agents_dir"],
            skill_dir=env_str(ENV.SKILL_DIR, local_defaults["skill_dir"]) or local_defaults["skill_dir"],
            user_dir=env_str(ENV.USER_DIR, local_defaults["user_dir"]) or local_defaults["user_dir"],
            db_type=env_str(ENV.DB_TYPE, StartupConfig.db_type) or StartupConfig.db_type,
            db_file=env_str(ENV.DB_FILE, local_defaults["db_file"]) or local_defaults["db_file"],
            preset_mcp_config=env_str(ENV.PRESET_MCP_CONFIG, StartupConfig.preset_mcp_config) or StartupConfig.preset_mcp_config,
            preset_running_config=env_str(ENV.PRESET_RUNNING_CONFIG, StartupConfig.preset_running_config) or StartupConfig.preset_running_config,
            default_llm_api_key=env_str(ENV.DEFAULT_LLM_API_KEY, StartupConfig.default_llm_api_key) or StartupConfig.default_llm_api_key,
            default_llm_api_base_url=env_str(ENV.DEFAULT_LLM_API_BASE_URL, StartupConfig.default_llm_api_base_url) or StartupConfig.default_llm_api_base_url,
            default_llm_model_name=env_str(ENV.DEFAULT_LLM_MODEL_NAME, StartupConfig.default_llm_model_name) or StartupConfig.default_llm_model_name,
            default_llm_max_tokens=env_int(ENV.DEFAULT_LLM_MAX_TOKENS, StartupConfig.default_llm_max_tokens),
            default_llm_temperature=env_float(ENV.DEFAULT_LLM_TEMPERATURE, StartupConfig.default_llm_temperature),
            default_llm_max_model_len=env_int(ENV.DEFAULT_LLM_MAX_MODEL_LEN, StartupConfig.default_llm_max_model_len),
            default_llm_top_p=env_float(ENV.DEFAULT_LLM_TOP_P, StartupConfig.default_llm_top_p),
            default_llm_presence_penalty=env_float(ENV.DEFAULT_LLM_PRESENCE_PENALTY, StartupConfig.default_llm_presence_penalty),
            context_history_ratio=env_float(ENV.CONTEXT_HISTORY_RATIO, StartupConfig.context_history_ratio),
            context_active_ratio=env_float(ENV.CONTEXT_ACTIVE_RATIO, StartupConfig.context_active_ratio),
            context_max_new_message_ratio=env_float(ENV.CONTEXT_MAX_NEW_MESSAGE_RATIO, StartupConfig.context_max_new_message_ratio),
            context_recent_turns=env_int(ENV.CONTEXT_RECENT_TURNS, StartupConfig.context_recent_turns),
            jwt_key=env_str(ENV.JWT_KEY, StartupConfig.jwt_key) or StartupConfig.jwt_key,
            jwt_expire_hours=env_int(ENV.JWT_EXPIRE_HOURS, StartupConfig.jwt_expire_hours),
            refresh_token_secret=env_str(ENV.REFRESH_TOKEN_SECRET, StartupConfig.refresh_token_secret) or StartupConfig.refresh_token_secret,
            embed_api_key=env_str(ENV.EMBEDDING_API_KEY, StartupConfig.embed_api_key),
            embed_base_url=env_str(ENV.EMBEDDING_BASE_URL, StartupConfig.embed_base_url),
            embed_model=env_str(ENV.EMBEDDING_MODEL, StartupConfig.embed_model) or StartupConfig.embed_model,
            embed_dims=env_int(ENV.EMBEDDING_DIMS, StartupConfig.embed_dims),
            s3_endpoint=env_str(ENV.S3_ENDPOINT, StartupConfig.s3_endpoint),
            s3_access_key=env_str(ENV.S3_ACCESS_KEY, StartupConfig.s3_access_key),
            s3_secret_key=env_str(ENV.S3_SECRET_KEY, StartupConfig.s3_secret_key),
            s3_secure=env_bool(ENV.S3_SECURE, StartupConfig.s3_secure),
            s3_bucket_name=env_str(ENV.S3_BUCKET_NAME, StartupConfig.s3_bucket_name),
            s3_public_base_url=env_str(ENV.S3_PUBLIC_BASE_URL, StartupConfig.s3_public_base_url),
        )
        return _normalize_paths(cfg)

    cfg = StartupConfig(
        app_mode="server",
        env=env_str(ENV.APP_ENV, StartupConfig.env) or StartupConfig.env,
        auth_mode=env_str(ENV.AUTH_MODE, StartupConfig.auth_mode) or StartupConfig.auth_mode,
        port=env_int(ENV.PORT, StartupConfig.port),
        logs_dir=env_str(ENV.LOGS_DIR, StartupConfig.logs_dir),
        session_dir=env_str(ENV.SESSION_DIR, StartupConfig.session_dir),
        agents_dir=env_str(ENV.AGENTS_DIR, StartupConfig.agents_dir),
        skill_dir=env_str(ENV.SKILL_DIR, StartupConfig.skill_dir),
        user_dir=env_str(ENV.USER_DIR, StartupConfig.user_dir),
        db_type=env_str(ENV.DB_TYPE, StartupConfig.db_type),
        db_file=env_str(ENV.DB_FILE, StartupConfig.db_file),
        mysql_host=env_str(ENV.MYSQL_HOST, StartupConfig.mysql_host),
        mysql_port=env_int(ENV.MYSQL_PORT, StartupConfig.mysql_port),
        mysql_user=env_str(ENV.MYSQL_USER, StartupConfig.mysql_user),
        mysql_password=env_str(ENV.MYSQL_PASSWORD, StartupConfig.mysql_password),
        mysql_database=env_str(ENV.MYSQL_DATABASE, StartupConfig.mysql_database),
        mysql_charset=StartupConfig.mysql_charset,
        default_llm_api_key=env_str(ENV.DEFAULT_LLM_API_KEY, StartupConfig.default_llm_api_key),
        default_llm_api_base_url=env_str(ENV.DEFAULT_LLM_API_BASE_URL, StartupConfig.default_llm_api_base_url),
        default_llm_model_name=env_str(ENV.DEFAULT_LLM_MODEL_NAME, StartupConfig.default_llm_model_name),
        default_llm_max_tokens=env_int(ENV.DEFAULT_LLM_MAX_TOKENS, StartupConfig.default_llm_max_tokens),
        default_llm_temperature=env_float(ENV.DEFAULT_LLM_TEMPERATURE, StartupConfig.default_llm_temperature),
        default_llm_max_model_len=env_int(ENV.DEFAULT_LLM_MAX_MODEL_LEN, StartupConfig.default_llm_max_model_len),
        default_llm_top_p=env_float(ENV.DEFAULT_LLM_TOP_P, StartupConfig.default_llm_top_p),
        default_llm_presence_penalty=env_float(ENV.DEFAULT_LLM_PRESENCE_PENALTY, StartupConfig.default_llm_presence_penalty),
        context_history_ratio=env_float(ENV.CONTEXT_HISTORY_RATIO, StartupConfig.context_history_ratio),
        context_active_ratio=env_float(ENV.CONTEXT_ACTIVE_RATIO, StartupConfig.context_active_ratio),
        context_max_new_message_ratio=env_float(ENV.CONTEXT_MAX_NEW_MESSAGE_RATIO, StartupConfig.context_max_new_message_ratio),
        context_recent_turns=env_int(ENV.CONTEXT_RECENT_TURNS, StartupConfig.context_recent_turns),
        auth_providers_json=env_str(ENV.AUTH_PROVIDERS, StartupConfig.auth_providers_json),
        trusted_identity_proxy_ips=env_csv(ENV.TRUSTED_IDENTITY_PROXY_IPS),
        bootstrap_admin_username=env_str(ENV.BOOTSTRAP_ADMIN_USERNAME, StartupConfig.bootstrap_admin_username) or StartupConfig.bootstrap_admin_username,
        bootstrap_admin_password=env_str(ENV.BOOTSTRAP_ADMIN_PASSWORD, StartupConfig.bootstrap_admin_password) or StartupConfig.bootstrap_admin_password,
        jwt_key=env_str(ENV.JWT_KEY, StartupConfig.jwt_key),
        jwt_expire_hours=env_int(ENV.JWT_EXPIRE_HOURS, StartupConfig.jwt_expire_hours),
        refresh_token_secret=env_str(ENV.REFRESH_TOKEN_SECRET, StartupConfig.refresh_token_secret),
        session_secret=env_str(ENV.SESSION_SECRET, StartupConfig.session_secret),
        session_cookie_name=env_str(ENV.SESSION_COOKIE_NAME, StartupConfig.session_cookie_name),
        session_cookie_secure=env_bool(ENV.SESSION_COOKIE_SECURE, StartupConfig.session_cookie_secure),
        session_cookie_same_site=(env_str(ENV.SESSION_COOKIE_SAME_SITE, StartupConfig.session_cookie_same_site) or StartupConfig.session_cookie_same_site).strip().lower(),
        cors_allowed_origins=env_csv(ENV.CORS_ALLOWED_ORIGINS, StartupConfig().cors_allowed_origins),
        cors_allow_credentials=env_bool(ENV.CORS_ALLOW_CREDENTIALS, StartupConfig.cors_allow_credentials),
        cors_allow_methods=env_csv(ENV.CORS_ALLOW_METHODS, StartupConfig().cors_allow_methods),
        cors_allow_headers=env_csv(ENV.CORS_ALLOW_HEADERS, StartupConfig().cors_allow_headers),
        cors_expose_headers=env_csv(ENV.CORS_EXPOSE_HEADERS, StartupConfig().cors_expose_headers),
        cors_max_age=env_int(ENV.CORS_MAX_AGE, StartupConfig.cors_max_age),
        web_base_path=env_str(ENV.WEB_BASE_PATH, StartupConfig.web_base_path),
        oauth2_clients_json=env_str(ENV.OAUTH2_CLIENTS, StartupConfig.oauth2_clients_json),
        oauth2_issuer=env_str(ENV.OAUTH2_ISSUER, StartupConfig.oauth2_issuer),
        oauth2_access_token_expires_in=env_int(ENV.OAUTH2_ACCESS_TOKEN_EXPIRES_IN, StartupConfig.oauth2_access_token_expires_in),
        eml_endpoint=env_str(ENV.EML_ENDPOINT, StartupConfig.eml_endpoint) or StartupConfig.eml_endpoint,
        eml_access_key_id=env_str(ENV.EML_ACCESS_KEY_ID, StartupConfig.eml_access_key_id),
        eml_access_key_secret=env_str(ENV.EML_ACCESS_KEY_SECRET, StartupConfig.eml_access_key_secret),
        eml_security_token=env_str(ENV.EML_SECURITY_TOKEN, StartupConfig.eml_security_token),
        eml_account_name=env_str(ENV.EML_ACCOUNT_NAME, StartupConfig.eml_account_name),
        eml_template_id=env_str(ENV.EML_TEMPLATE_ID, StartupConfig.eml_template_id),
        eml_register_subject=env_str(ENV.EML_REGISTER_SUBJECT, StartupConfig.eml_register_subject) or StartupConfig.eml_register_subject,
        eml_address_type=env_int(ENV.EML_ADDRESS_TYPE, StartupConfig.eml_address_type) or StartupConfig.eml_address_type,
        eml_reply_to_address=env_bool(ENV.EML_REPLY_TO_ADDRESS, StartupConfig.eml_reply_to_address),
        embed_api_key=env_str(ENV.EMBEDDING_API_KEY, StartupConfig.embed_api_key),
        embed_base_url=env_str(ENV.EMBEDDING_BASE_URL, StartupConfig.embed_base_url),
        embed_model=env_str(ENV.EMBEDDING_MODEL, StartupConfig.embed_model) or StartupConfig.embed_model,
        embed_dims=env_int(ENV.EMBEDDING_DIMS, StartupConfig.embed_dims),
        es_url=env_str(ENV.ES_URL, StartupConfig.es_url),
        es_api_key=env_str(ENV.ES_API_KEY, StartupConfig.es_api_key),
        es_username=env_str(ENV.ES_USERNAME, StartupConfig.es_username),
        es_password=env_str(ENV.ES_PASSWORD, StartupConfig.es_password),
        s3_endpoint=env_str(ENV.S3_ENDPOINT, StartupConfig.s3_endpoint),
        s3_access_key=env_str(ENV.S3_ACCESS_KEY, StartupConfig.s3_access_key),
        s3_secret_key=env_str(ENV.S3_SECRET_KEY, StartupConfig.s3_secret_key),
        s3_secure=env_bool(ENV.S3_SECURE, StartupConfig.s3_secure),
        s3_bucket_name=env_str(ENV.S3_BUCKET_NAME, StartupConfig.s3_bucket_name),
        s3_public_base_url=env_str(ENV.S3_PUBLIC_BASE_URL, StartupConfig.s3_public_base_url),
        trace_jaeger_endpoint=env_str(
            ENV.TRACE_JAEGER_URL,
            env_str(ENV.TRACE_JAEGER_ENDPOINT, StartupConfig.trace_jaeger_endpoint),
        ),
        trace_jaeger_public_url=env_str(ENV.TRACE_JAEGER_PUBLIC_URL, StartupConfig.trace_jaeger_public_url),
    )

    same_site = (cfg.session_cookie_same_site or StartupConfig.session_cookie_same_site).strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        cfg.session_cookie_same_site = StartupConfig.session_cookie_same_site
    if is_production_like(cfg):
        cfg.session_cookie_secure = True
    if cfg.web_base_path:
        cfg.web_base_path = "/" + cfg.web_base_path.strip("/")
    else:
        cfg.web_base_path = StartupConfig.web_base_path

    cfg = _normalize_paths(cfg)
    return cfg


def get_startup_config() -> StartupConfig:
    return _GLOBAL_STARTUP_CONFIG


def init_startup_config(mode: str = "server") -> StartupConfig:
    global _GLOBAL_STARTUP_CONFIG
    cfg = build_startup_config(mode)
    validate_startup_config(cfg)
    _GLOBAL_STARTUP_CONFIG = cfg
    return cfg
