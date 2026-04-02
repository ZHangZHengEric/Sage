import pytest

from common.core import config


def test_production_like_config_rejects_default_secrets(monkeypatch):
    monkeypatch.setenv("SAGE_ENV", "production")
    monkeypatch.delenv("SAGE_JWT_KEY", raising=False)
    monkeypatch.delenv("SAGE_REFRESH_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("SAGE_SESSION_SECRET", raising=False)

    cfg = config.build_startup_config()

    with pytest.raises(ValueError, match="secure secrets"):
        config.validate_startup_config(cfg)


def test_production_like_config_forces_secure_session_cookie(monkeypatch):
    monkeypatch.setenv("SAGE_ENV", "production")
    monkeypatch.setenv("SAGE_JWT_KEY", "prod-jwt-secret")
    monkeypatch.setenv("SAGE_REFRESH_TOKEN_SECRET", "prod-refresh-secret")
    monkeypatch.setenv("SAGE_SESSION_SECRET", "prod-session-secret")
    monkeypatch.setenv("SAGE_SESSION_COOKIE_SECURE", "false")

    cfg = config.build_startup_config()

    assert cfg.session_cookie_secure is True


def test_development_config_allows_default_secrets(monkeypatch):
    monkeypatch.setenv("SAGE_ENV", "development")
    monkeypatch.delenv("SAGE_JWT_KEY", raising=False)
    monkeypatch.delenv("SAGE_REFRESH_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("SAGE_SESSION_SECRET", raising=False)

    cfg = config.build_startup_config()

    config.validate_startup_config(cfg)
