from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.v2.server.observability.logging import get_logger

LOGGER = get_logger(__name__)

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


def _jwt_secret() -> str:
    secret = _env("SAGE_SERVER_JWT_SECRET", DEFAULT_JWT_SECRET)
    if secret == DEFAULT_JWT_SECRET:
        LOGGER.warning(
            "server.jwt.default_secret",
            "using built-in JWT secret; set SAGE_SERVER_JWT_SECRET in production"
        )
    elif len(secret.encode()) < 32:
        LOGGER.warning("server.jwt.short_secret", "SAGE_SERVER_JWT_SECRET is shorter than 32 bytes")
    return secret


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
    log_level: str = "info"
    log_format: str = "json"
    log_directory: str = "./logs"
    mysql_url: str | None = None
    jaeger_url: str | None = None
    jaeger_service_name: str = "sage-server"
    jaeger_public_url: str = "http://127.0.0.1:16686/jaeger"
    trace_backend: str | None = None
    trace_otlp_endpoint: str = ""
    trace_otlp_protocol: str = "grpc"
    trace_otlp_insecure: bool = False
    trace_service_name: str = "sage-server"
    trace_environment: str = "production"
    trace_content_mode: str = "redacted"
    trace_max_content_chars: int = 16384
    trace_sample_rate: float = 1.0
    trace_timeout_seconds: float = 3.0
    langfuse_base_url: str = ""
    langfuse_public_url: str = ""
    langfuse_public_key_env: str = "LANGFUSE_PUBLIC_KEY"
    langfuse_secret_key_env: str = "LANGFUSE_SECRET_KEY"
    langfuse_ingestion_version: int = 4
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
    approval_timeout_seconds: int = 86400

    def __post_init__(self) -> None:
        if self.trace_backend not in {None, "noop", "otlp", "langfuse"}:
            raise ValueError("trace_backend must be noop, otlp or langfuse")
        if self.trace_otlp_protocol not in {"grpc", "http"}:
            raise ValueError("trace_otlp_protocol must be grpc or http")
        if self.trace_content_mode not in {"metadata", "redacted"}:
            raise ValueError("trace_content_mode must be metadata or redacted")
        if not 0 <= self.trace_sample_rate <= 1:
            raise ValueError("trace_sample_rate must be between 0 and 1")
        if not 256 <= self.trace_max_content_chars <= 65536 or not 0 < self.trace_timeout_seconds <= 30:
            raise ValueError("invalid trace content limit or timeout")
        if self.effective_trace_backend == "otlp" and not (self.trace_otlp_endpoint or self.jaeger_url):
            raise ValueError("OTLP tracing requires an endpoint")
        if self.effective_trace_backend == "langfuse" and not self.langfuse_base_url:
            raise ValueError("Langfuse tracing requires a base URL")
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
        if self.effective_trace_backend == "langfuse":
            return self.langfuse_public_url or self.langfuse_base_url
        if self.effective_trace_backend == "otlp" and self.jaeger_url:
            return self.jaeger_public_url
        return ""

    def database_url(self) -> str:
        if not self.mysql_url:
            raise ValueError("MySQL URL is required")
        url = self.mysql_url
        if url.startswith("mysql://"):
            return "mysql+aiomysql://" + url[len("mysql://") :]
        return url

    @classmethod
    def from_env(cls, *, data_root: Path | None = None) -> ServerSettings:
        mysql_url = _env("SAGE_SERVER_MYSQL_URL")
        if not mysql_url:
            raise ValueError("SAGE_SERVER_MYSQL_URL is required")
        root = data_root or Path(_env("SAGE_SERVER_DATA", "data/server_v2"))
        return cls(
            host=_env("SAGE_SERVER_HOST", "127.0.0.1"),
            port=int(_env("SAGE_SERVER_PORT", "8090")),
            data_root=root.expanduser().resolve(),
            jwt_secret=_jwt_secret(),
            jwt_expire_hours=int(_env("SAGE_SERVER_JWT_EXPIRE_HOURS", "72")),
            language=_env("SAGE_SERVER_LANGUAGE", "zh"),
            admin_username=_env("SAGE_SERVER_ADMIN_USERNAME", "admin"),
            admin_password=_env("SAGE_SERVER_ADMIN_PASSWORD", "admin12345"),
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
            log_directory=_env("SAGE_SERVER_LOG_DIRECTORY", "./logs"),
            max_concurrent_runs=int(_env("SAGE_SERVER_MAX_CONCURRENT_RUNS", "8")),
            max_concurrent_runs_per_user=int(
                _env("SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER", "2")
            ),
            max_pending_runs=int(_env("SAGE_SERVER_MAX_PENDING_RUNS", "1024")),
            max_model_clients=int(_env("SAGE_SERVER_MAX_MODEL_CLIENTS", "64")),
            max_managed_applications=int(_env("SAGE_SERVER_MAX_MANAGED_APPLICATIONS", "32")),
            max_managed_builds=int(_env("SAGE_SERVER_MAX_MANAGED_BUILDS", "4")),
            execution_shell_mode=_choice_env("SAGE_SERVER_EXECUTION_SHELL_MODE", "sandboxed", frozenset({"ask", "sandboxed", "deny"})),
            approval_timeout_seconds=int(_env("SAGE_SERVER_APPROVAL_TIMEOUT_SECONDS", "86400")),
            mysql_url=mysql_url,
            trace_backend=_env("SAGE_SERVER_TRACE_BACKEND") or None,
            trace_otlp_endpoint=_env("SAGE_SERVER_TRACE_OTLP_ENDPOINT"),
            trace_otlp_protocol=_env("SAGE_SERVER_TRACE_OTLP_PROTOCOL", "grpc"),
            trace_otlp_insecure=_env("SAGE_SERVER_TRACE_OTLP_INSECURE", "false").lower() == "true",
            trace_service_name=_env("SAGE_SERVER_TRACE_SERVICE_NAME", "sage-server"),
            trace_environment=_env("SAGE_SERVER_TRACE_ENVIRONMENT", "production"),
            trace_content_mode=_env("SAGE_SERVER_TRACE_CONTENT_MODE", "redacted"),
            trace_max_content_chars=int(_env("SAGE_SERVER_TRACE_MAX_CONTENT_CHARS", "16384")),
            trace_sample_rate=float(_env("SAGE_SERVER_TRACE_SAMPLE_RATE", "1")),
            trace_timeout_seconds=float(_env("SAGE_SERVER_TRACE_TIMEOUT_SECONDS", "3")),
            langfuse_base_url=_env("SAGE_SERVER_LANGFUSE_BASE_URL"),
            langfuse_public_url=_env("SAGE_SERVER_LANGFUSE_PUBLIC_URL"),
            langfuse_public_key_env=_env("SAGE_SERVER_LANGFUSE_PUBLIC_KEY_ENV", "LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key_env=_env("SAGE_SERVER_LANGFUSE_SECRET_KEY_ENV", "LANGFUSE_SECRET_KEY"),
            langfuse_ingestion_version=int(_env("SAGE_SERVER_LANGFUSE_INGESTION_VERSION", "4")),
            jaeger_url=_env("SAGE_SERVER_JAEGER_URL") or None,
            jaeger_service_name=_env("SAGE_SERVER_JAEGER_SERVICE_NAME", "sage-server"),
            jaeger_public_url=_env(
                "SAGE_SERVER_JAEGER_PUBLIC_URL",
                "http://127.0.0.1:16686/jaeger",
            ),
            public_base_url=_env("SAGE_SERVER_PUBLIC_URL", "").rstrip("/"),
        )
