from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.server.core import config
from app.server.core.middleware import register_middlewares


def _build_app() -> FastAPI:
    app = FastAPI()
    register_middlewares(app)

    @app.get("/api/protected")
    async def protected():
        return {"ok": True}

    return app


def test_default_cors_configuration_uses_public_wildcard_without_credentials():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig()
    app = _build_app()

    cors_layers = [layer for layer in app.user_middleware if layer.cls is CORSMiddleware]

    assert len(cors_layers) == 1
    assert cors_layers[0].kwargs["allow_credentials"] is False
    assert cors_layers[0].kwargs["allow_origins"] == ["*"]
    assert cors_layers[0].kwargs["allow_methods"] == ["*"]
    assert cors_layers[0].kwargs["allow_headers"] == ["*"]
    assert cors_layers[0].kwargs["expose_headers"] == []
    assert cors_layers[0].kwargs["max_age"] == 600


def test_cors_configuration_can_override_all_major_settings():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig(
        cors_allowed_origins=["https://app.example.com"],
        cors_allow_credentials=False,
        cors_allow_methods=["GET", "POST"],
        cors_allow_headers=["Authorization", "Content-Type"],
        cors_expose_headers=["X-Trace-Id"],
        cors_max_age=120,
    )
    app = _build_app()

    cors_layers = [layer for layer in app.user_middleware if layer.cls is CORSMiddleware]

    assert len(cors_layers) == 1
    assert cors_layers[0].kwargs["allow_origins"] == ["https://app.example.com"]
    assert cors_layers[0].kwargs["allow_credentials"] is False
    assert cors_layers[0].kwargs["allow_methods"] == ["GET", "POST"]
    assert cors_layers[0].kwargs["allow_headers"] == ["Authorization", "Content-Type"]
    assert cors_layers[0].kwargs["expose_headers"] == ["X-Trace-Id"]
    assert cors_layers[0].kwargs["max_age"] == 120


def test_cors_preflight_allows_only_configured_origins():
    config._GLOBAL_STARTUP_CONFIG = config.StartupConfig(
        cors_allowed_origins=["https://app.example.com"],
    )
    app = _build_app()

    with TestClient(app) as client:
        allowed = client.options(
            "/api/protected",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/api/protected",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "access-control-allow-origin" not in denied.headers
