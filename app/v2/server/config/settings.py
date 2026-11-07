from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_JWT_SECRET = "dev-only-change-me-sage-server-jwt-secret"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _choice_env(name: str, default: str, choices: frozenset[str]) -> str:
    value = _env(name, default).lower()
    if value == "warn":
        value = "warning"
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {expected}")
    return value


@dataclass(frozen=True, slots=True)
class ServerSettings:
    host: str
    port: int
    data_root: Path
    jwt_secret: str
    jwt_expire_hours: int
    language: str
    admin_username: str
    admin_password: str
    cookie_secure: bool = True
    log_level: str = "debug"
    log_format: str = "json"
    log_directory: str = ""
    mysql_url: str | None = None
    postgres_url: str | None = field(default=None, repr=False)
    redis_url: str | None = None
    session_store_plugin: str | None = None
    session_store_key_prefix: str | None = None
    scheduler_plugin: str = "sage.scheduler.ephemeral"
    jaeger_url: str | None = None
    jaeger_service_name: str = "sage-server"
    jaeger_public_url: str = "http://127.0.0.1:16686/jaeger"
    trace_backend: str | None = None
    trace_otlp_endpoint: str = ""
    trace_otlp_protocol: str = "grpc"
    trace_otlp_insecure: bool = False
    trace_service_name: str = "sage-server"
    trace_environment: str = "production"
    trace_content_mode: str | None = None
    trace_max_content_chars: int = 16384
    trace_sample_rate: float = 1.0
    trace_timeout_seconds: float = 3.0
    trace_query_url: str = ""
    trace_query_headers_env: str = "OTEL_EXPORTER_OTLP_TRACES_HEADERS"
    langfuse_base_url: str = ""
    langfuse_public_url: str = ""
    langfuse_public_key_env: str = "LANGFUSE_PUBLIC_KEY"
    langfuse_secret_key_env: str = "LANGFUSE_SECRET_KEY"
    langfuse_ingestion_version: int = 4
    phoenix_endpoint: str = ""
    phoenix_public_url: str = ""
    phoenix_project_name: str = "sage"
    phoenix_api_key_env: str = "PHOENIX_API_KEY"
    # The address clients reach this server at. Only A2A needs it: an Agent
    # Card must publish an absolute URL, and behind a proxy the request's own
    # host header is the proxy's, not the one a peer agent can call back on.
    # Empty means "trust the request", which is right for direct deployments.
    public_base_url: str = ""

    max_concurrent_runs: int = 8
    max_concurrent_runs_per_user: int = 2
    max_pending_runs: int = 1024
    max_model_clients: int = 64
    max_managed_applications: int = 32
    max_managed_builds: int = 4
    execution_shell_mode: str = "sandboxed"
    sandbox_plugin: str = "sage.sandbox.local-workspace"
    cube_api_url: str = ""
    cube_template_id: str = ""
    cube_proxy_node_ip: str = ""
    cube_api_key: str | None = field(default=None, repr=False)
    cube_volume_driver: str | None = None
    # Host-only ceiling; deliberately has no environment-variable binding.
    sandbox_network_mode: str = "unrestricted"
    linux_execution_uid: int | None = None
    linux_execution_gid: int | None = None
    approval_timeout_seconds: int = 86400
    # Startup snapshot; never read mutable configuration files during a Run.
    plugin_overrides: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.sandbox_plugin not in {"sage.sandbox.local-workspace", "sage.sandbox.cube-volume"}:
            raise ValueError("Unsupported Server sandbox_plugin")
        if self.sandbox_plugin == "sage.sandbox.cube-volume":
            from urllib.parse import urlsplit
            endpoint = urlsplit(self.cube_api_url)
            if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username
                    or endpoint.password or endpoint.query or endpoint.fragment
                    or not self.cube_template_id or not self.cube_proxy_node_ip):
                raise ValueError("Cube execution requires an API URL, template ID and proxy node IP")
            if self.scheduler_plugin != "sage.scheduler.ephemeral":
                raise ValueError("Cube execution currently requires a single Server with the ephemeral scheduler")
        if (len(self.jwt_secret.encode()) < 32 or self.jwt_secret == DEFAULT_JWT_SECRET
                or self.jwt_secret.startswith("replace-with-")):
            raise ValueError("SAGE_SERVER_JWT_SECRET must be a private secret of at least 32 bytes")
        if self.jwt_expire_hours <= 0:
            raise ValueError("SAGE_SERVER_JWT_EXPIRE_HOURS must be positive")
        if self.mysql_url and self.postgres_url:
            raise ValueError("Configure either mysql_url or postgres_url, not both")
        if self.postgres_url:
            from sagents.v2.runtime.session.plugins.postgres import parse_postgres_dsn
            parse_postgres_dsn(self.postgres_url)
            if self.session_store_plugin not in {None, "sage.session.postgres", "sage.session.redis-postgres"}:
                raise ValueError("postgres_url requires the PostgreSQL SessionStore")
        if self.session_store_plugin in {"sage.session.postgres", "sage.session.redis-postgres"} and not self.postgres_url:
            raise ValueError("PostgreSQL SessionStore requires postgres_url")
        if self.session_store_plugin not in {None, "sage.session.mysql", "sage.session.redis-mysql", "sage.session.postgres", "sage.session.redis-postgres"}:
            raise ValueError("Unsupported Server session_store_plugin")
        if self.session_store_plugin in {"sage.session.mysql", "sage.session.redis-mysql"} and not self.mysql_url:
            raise ValueError("session_store_plugin requires mysql_url")
        if self.session_store_plugin in {"sage.session.redis-mysql", "sage.session.redis-postgres"} and not self.redis_url:
            raise ValueError("Redis SessionStore plugin requires redis_url")
        if self.redis_url and not self.session_database_url:
            raise ValueError("redis_url requires mysql_url or postgres_url for Session archival")
        if self.scheduler_plugin not in {"sage.scheduler.ephemeral", "sage.scheduler.redis-distributed"}:
            raise ValueError("Unsupported Server scheduler_plugin")
        if self.scheduler_plugin == "sage.scheduler.redis-distributed" and (
            not self.redis_session_store
        ):
            raise ValueError("Distributed scheduler requires Redis + SQL SessionStore")
        if self.session_store_key_prefix is not None and (
            not self.session_store_key_prefix.strip() or not self.redis_session_store
        ):
            raise ValueError("session_store_key_prefix requires Redis + SQL SessionStore and a nonempty prefix")
        if self.sandbox_network_mode not in {"none", "unrestricted"}:
            raise ValueError("sandbox_network_mode must be none or unrestricted")
        ids = (self.linux_execution_uid, self.linux_execution_gid)
        if any(value is not None for value in ids) and not all(
            type(value) is int and 0 < value < 2**32 - 1 for value in ids
        ):
            raise ValueError("linux_execution_uid and linux_execution_gid must both be positive non-root IDs")
        if self.trace_backend not in {None, "noop", "otlp", "langfuse", "phoenix"}:
            raise ValueError("trace_backend must be noop, otlp, langfuse or phoenix")
        if self.trace_otlp_protocol not in {"grpc", "http"}:
            raise ValueError("trace_otlp_protocol must be grpc or http")
        if self.trace_content_mode not in {None, "metadata", "redacted", "raw"}:
            raise ValueError("trace_content_mode must be metadata, redacted or raw")
        if not 0 <= self.trace_sample_rate <= 1:
            raise ValueError("trace_sample_rate must be between 0 and 1")
        if not 256 <= self.trace_max_content_chars <= 65536 or not 0 < self.trace_timeout_seconds <= 30:
            raise ValueError("invalid trace content limit or timeout")
        if self.effective_trace_backend == "otlp" and not (self.trace_otlp_endpoint or self.jaeger_url):
            raise ValueError("OTLP tracing requires an endpoint")
        if self.effective_trace_backend == "langfuse" and not self.langfuse_base_url:
            raise ValueError("Langfuse tracing requires a base URL")
        if self.effective_trace_backend == "phoenix" and not self.phoenix_endpoint:
            raise ValueError("Phoenix tracing requires an endpoint")
        if self.langfuse_ingestion_version not in {3, 4}:
            raise ValueError("langfuse_ingestion_version must be 3 or 4")
        if self.execution_shell_mode not in {"ask", "sandboxed", "deny"}:
            raise ValueError("execution_shell_mode must be ask, sandboxed or deny")
        if not 60 <= self.approval_timeout_seconds <= 604800:
            raise ValueError("approval timeout must be between 60 and 604800 seconds")
        if min(self.max_managed_applications, self.max_managed_builds) < 1:
            raise ValueError("managed application and build limits must be positive")
        if self.max_model_clients < 1:
            raise ValueError("max_model_clients must be positive")
        if (
            min(
                self.max_concurrent_runs,
                self.max_concurrent_runs_per_user,
                self.max_pending_runs,
            )
            < 1
        ):
            raise ValueError("server run concurrency and queue limits must be positive")

    @property
    def effective_trace_backend(self) -> str:
        return self.trace_backend or ("otlp" if self.jaeger_url else "noop")

    @property
    def trace_console_url(self) -> str:
        if self.effective_trace_backend == "phoenix":
            return self.phoenix_public_url
        if self.effective_trace_backend == "langfuse":
            return self.langfuse_public_url or self.langfuse_base_url
        if self.effective_trace_backend == "otlp" and self.jaeger_url:
            return self.jaeger_public_url
        return ""

    @property
    def effective_session_store_plugin(self) -> str:
        if self.session_store_plugin:
            return self.session_store_plugin
        backend = "postgres" if self.postgres_url else "mysql"
        return "sage.session." + ("redis-" if self.redis_url else "") + backend

    @property
    def redis_session_store(self) -> bool:
        return bool(self.session_database_url and self.redis_url and self.effective_session_store_plugin in {
            "sage.session.redis-mysql", "sage.session.redis-postgres",
        })

    @property
    def session_database_url(self) -> str | None:
        return self.postgres_url or self.mysql_url

    def database_url(self) -> str:
        if self.postgres_url:
            from sagents.v2.runtime.session.plugins.postgres import parse_postgres_dsn
            return parse_postgres_dsn(self.postgres_url).replace("postgresql://", "postgresql+psycopg://", 1)
        if not self.mysql_url:
            raise ValueError("MySQL URL is required")
        url = self.mysql_url
        if url.startswith("mysql://"):
            return "mysql+aiomysql://" + url[len("mysql://") :]
        return url

    @classmethod
    def from_env(cls, *, data_root: Path | None = None) -> ServerSettings:
        mysql_url = _env("SAGE_SERVER_MYSQL_URL")
        postgres_url = _env("SAGE_SERVER_POSTGRES_URL")
        if not mysql_url and not postgres_url:
            raise ValueError("SAGE_SERVER_MYSQL_URL is required unless SAGE_SERVER_POSTGRES_URL is set")
        root = data_root or Path(_env("SAGE_SERVER_DATA", "data/server_v2"))
        return cls(
            host=_env("SAGE_SERVER_HOST", "127.0.0.1"),
            port=int(_env("SAGE_SERVER_PORT", "8090")),
            data_root=root.expanduser().resolve(),
            jwt_secret=_env("SAGE_SERVER_JWT_SECRET"),
            jwt_expire_hours=int(_env("SAGE_SERVER_JWT_EXPIRE_HOURS", "72")),
            language=_env("SAGE_SERVER_LANGUAGE", "zh"),
            admin_username=_env("SAGE_SERVER_ADMIN_USERNAME", "admin"),
            admin_password=_env("SAGE_SERVER_ADMIN_PASSWORD"),
            cookie_secure=_choice_env("SAGE_SERVER_COOKIE_SECURE", "true", frozenset({"true", "false"})) == "true",
            log_level=_choice_env(
                "SAGE_SERVER_LOG_LEVEL",
                "info",
                frozenset({"debug", "info", "warning", "error", "critical"}),
            ),
            log_format=_choice_env(
                "SAGE_SERVER_LOG_FORMAT",
                "json",
                frozenset({"json", "text"}),
            ),
            log_directory=_env("SAGE_SERVER_LOG_DIRECTORY", ""),
            max_concurrent_runs=int(_env("SAGE_SERVER_MAX_CONCURRENT_RUNS", "8")),
            max_concurrent_runs_per_user=int(
                _env("SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER", "2")
            ),
            max_pending_runs=int(_env("SAGE_SERVER_MAX_PENDING_RUNS", "1024")),
            max_model_clients=int(_env("SAGE_SERVER_MAX_MODEL_CLIENTS", "64")),
            max_managed_applications=int(_env("SAGE_SERVER_MAX_MANAGED_APPLICATIONS", "32")),
            max_managed_builds=int(_env("SAGE_SERVER_MAX_MANAGED_BUILDS", "4")),
            execution_shell_mode=_choice_env("SAGE_SERVER_EXECUTION_SHELL_MODE", "sandboxed", frozenset({"ask", "sandboxed", "deny"})),
            sandbox_plugin=_env("SAGE_SERVER_SANDBOX_PLUGIN", "sage.sandbox.local-workspace"),
            cube_api_url=_env("SAGE_SERVER_CUBE_API_URL"),
            cube_template_id=_env("SAGE_SERVER_CUBE_TEMPLATE_ID"),
            cube_proxy_node_ip=_env("SAGE_SERVER_CUBE_PROXY_NODE_IP"),
            cube_api_key=_env("SAGE_SERVER_CUBE_API_KEY") or None,
            cube_volume_driver=_env("SAGE_SERVER_CUBE_VOLUME_DRIVER") or None,
            approval_timeout_seconds=int(_env("SAGE_SERVER_APPROVAL_TIMEOUT_SECONDS", "86400")),
            linux_execution_uid=int(value) if (value := _env("SAGE_SERVER_LINUX_EXECUTION_UID")) else None,
            linux_execution_gid=int(value) if (value := _env("SAGE_SERVER_LINUX_EXECUTION_GID")) else None,
            mysql_url=mysql_url or None,
            postgres_url=postgres_url or None,
            redis_url=_env("SAGE_SERVER_REDIS_URL") or None,
            session_store_plugin=_env("SAGE_SERVER_SESSION_STORE_PLUGIN") or None,
            session_store_key_prefix=_env("SAGE_SERVER_SESSION_STORE_KEY_PREFIX") or None,
            scheduler_plugin=_env("SAGE_SERVER_SCHEDULER_PLUGIN", "sage.scheduler.ephemeral"),
            trace_backend=_env("SAGE_SERVER_TRACE_BACKEND") or None,
            trace_otlp_endpoint=_env("SAGE_SERVER_TRACE_OTLP_ENDPOINT"),
            trace_otlp_protocol=_env("SAGE_SERVER_TRACE_OTLP_PROTOCOL", "grpc"),
            trace_otlp_insecure=_env("SAGE_SERVER_TRACE_OTLP_INSECURE", "false").lower() == "true",
            trace_service_name=_env("SAGE_SERVER_TRACE_SERVICE_NAME", "sage-server"),
            trace_environment=_env("SAGE_SERVER_TRACE_ENVIRONMENT", "production"),
            trace_content_mode=_env("SAGE_SERVER_TRACE_CONTENT_MODE") or None,
            trace_max_content_chars=int(_env("SAGE_SERVER_TRACE_MAX_CONTENT_CHARS", "16384")),
            trace_sample_rate=float(_env("SAGE_SERVER_TRACE_SAMPLE_RATE", "1")),
            trace_timeout_seconds=float(_env("SAGE_SERVER_TRACE_TIMEOUT_SECONDS", "3")),
            trace_query_url=_env("SAGE_SERVER_TRACE_QUERY_URL"),
            trace_query_headers_env=_env("SAGE_SERVER_TRACE_QUERY_HEADERS_ENV", "OTEL_EXPORTER_OTLP_TRACES_HEADERS"),
            langfuse_base_url=_env("SAGE_SERVER_LANGFUSE_BASE_URL"),
            langfuse_public_url=_env("SAGE_SERVER_LANGFUSE_PUBLIC_URL"),
            langfuse_public_key_env=_env("SAGE_SERVER_LANGFUSE_PUBLIC_KEY_ENV", "LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key_env=_env("SAGE_SERVER_LANGFUSE_SECRET_KEY_ENV", "LANGFUSE_SECRET_KEY"),
            langfuse_ingestion_version=int(_env("SAGE_SERVER_LANGFUSE_INGESTION_VERSION", "4")),
            phoenix_endpoint=_env("SAGE_SERVER_PHOENIX_ENDPOINT"),
            phoenix_public_url=_env("SAGE_SERVER_PHOENIX_PUBLIC_URL"),
            phoenix_project_name=_env("SAGE_SERVER_PHOENIX_PROJECT_NAME", "sage"),
            phoenix_api_key_env=_env("SAGE_SERVER_PHOENIX_API_KEY_ENV", "PHOENIX_API_KEY"),
            jaeger_url=_env("SAGE_SERVER_JAEGER_URL") or None,
            jaeger_service_name=_env("SAGE_SERVER_JAEGER_SERVICE_NAME", "sage-server"),
            jaeger_public_url=_env(
                "SAGE_SERVER_JAEGER_PUBLIC_URL",
                "http://127.0.0.1:16686/jaeger",
            ),
            public_base_url=_env("SAGE_SERVER_PUBLIC_URL", "").rstrip("/"),
        )
