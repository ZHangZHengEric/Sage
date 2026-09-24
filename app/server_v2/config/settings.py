from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.server_v2.observability.logging import get_logger

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

    def __post_init__(self) -> None:
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
            mysql_url=mysql_url,
            jaeger_url=_env("SAGE_SERVER_JAEGER_URL") or None,
            jaeger_service_name=_env("SAGE_SERVER_JAEGER_SERVICE_NAME", "sage-server"),
            jaeger_public_url=_env(
                "SAGE_SERVER_JAEGER_PUBLIC_URL",
                "http://127.0.0.1:16686/jaeger",
            ),
            public_base_url=_env("SAGE_SERVER_PUBLIC_URL", "").rstrip("/"),
        )
