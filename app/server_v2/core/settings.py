from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "dev-only-change-me-sage-server-jwt-secret"
REDIS_KEY_PREFIX = "sage-server"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or not value.strip() else value.strip()


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _choice_env(name: str, default: str, choices: frozenset[str]) -> str:
    value = _env(name, default).lower()
    if value == "warn" and "warning" in choices:
        value = "warning"
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {expected}")
    return value


def _jwt_secret() -> str:
    secret = _env("SAGE_SERVER_JWT_SECRET", DEFAULT_JWT_SECRET)
    if secret == DEFAULT_JWT_SECRET:
        LOGGER.warning(
            "using built-in JWT secret; set SAGE_SERVER_JWT_SECRET in production"
        )
    elif len(secret.encode()) < 32:
        LOGGER.warning("SAGE_SERVER_JWT_SECRET is shorter than 32 bytes")
    return secret


@dataclass(frozen=True, slots=True)
class ServerV2Settings:
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
    log_directory: str | None = None
    mysql_url: str | None = None
    redis_url: str | None = None
    jaeger_url: str | None = None
    jaeger_service_name: str = "sage-server"
    jaeger_public_url: str = "http://127.0.0.1:16686/jaeger"

    def database_url(self) -> str | None:
        if not self.mysql_url:
            return None
        url = self.mysql_url
        if url.startswith("mysql://"):
            return "mysql+aiomysql://" + url[len("mysql://") :]
        return url

    @classmethod
    def from_env(cls, *, data_root: Path | None = None) -> ServerV2Settings:
        mysql_url = _optional_env("SAGE_SERVER_MYSQL_URL")
        redis_url = _optional_env("SAGE_SERVER_REDIS_URL")
        if not mysql_url:
            raise ValueError("SAGE_SERVER_MYSQL_URL is required")
        if not redis_url:
            raise ValueError("SAGE_SERVER_REDIS_URL is required")
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
            log_directory=_optional_env("SAGE_SERVER_LOG_DIRECTORY"),
            mysql_url=mysql_url,
            redis_url=redis_url,
            jaeger_url=_optional_env("SAGE_SERVER_JAEGER_URL"),
            jaeger_service_name=_env("SAGE_SERVER_JAEGER_SERVICE_NAME", "sage-server"),
            jaeger_public_url=_env(
                "SAGE_SERVER_JAEGER_PUBLIC_URL",
                "http://127.0.0.1:16686/jaeger",
            ),
        )
