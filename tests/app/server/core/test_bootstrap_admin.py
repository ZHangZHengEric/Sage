from app.server.core import config
from app.server.core.bootstrap_admin import (
    get_bootstrap_admin_spec,
    format_bootstrap_admin_log,
)


def test_bootstrap_admin_is_disabled_without_explicit_env(monkeypatch):
    monkeypatch.delenv("SAGE_BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("SAGE_BOOTSTRAP_ADMIN_PASSWORD", raising=False)

    cfg = config.build_startup_config()

    assert get_bootstrap_admin_spec(cfg) is None


def test_bootstrap_admin_uses_explicit_env(monkeypatch):
    monkeypatch.setenv("SAGE_BOOTSTRAP_ADMIN_USERNAME", "root-admin")
    monkeypatch.setenv("SAGE_BOOTSTRAP_ADMIN_PASSWORD", "SuperSecret123")

    cfg = config.build_startup_config()
    spec = get_bootstrap_admin_spec(cfg)

    assert spec is not None
    assert spec.username == "root-admin"
    assert spec.password == "SuperSecret123"


def test_bootstrap_admin_log_masks_password():
    spec = get_bootstrap_admin_spec(
        config.StartupConfig(
            bootstrap_admin_username="root-admin",
            bootstrap_admin_password="SuperSecret123",
        )
    )

    message = format_bootstrap_admin_log(spec)

    assert "root-admin" in message
    assert "SuperSecret123" not in message
    assert "***" in message
