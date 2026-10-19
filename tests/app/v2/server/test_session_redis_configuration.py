import pytest

from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.config.settings import ServerSettings
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from tests.app.v2.server.conftest import make_settings


def test_redis_session_selection_uses_existing_mysql_tables(tmp_path):
    settings = make_settings(tmp_path, mysql_url="mysql://localhost/sage", session_redis_url="redis://localhost/1")
    selected = server_v2_manifest(settings).runtime.capabilities["session.store"]
    assert selected.plugin == "sage.session.redis-mysql"
    assert selected.config == {"dsn": settings.mysql_url, "table_prefix": "", "redis_url": settings.session_redis_url}
    descriptor = builtin_extension_registry().get(selected.plugin).descriptor
    assert descriptor.config_schema["required"] == ["dsn", "redis_url"]


def test_mysql_selection_stays_available_without_redis(tmp_path):
    settings = make_settings(tmp_path, mysql_url="mysql://localhost/sage")
    assert server_v2_manifest(settings).runtime.capabilities["session.store"].plugin == "sage.session.mysql"


def test_redis_environment_requires_mysql_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://localhost/sage")
    monkeypatch.setenv("SAGE_SERVER_SESSION_REDIS_URL", "redis://localhost/1")
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.session_redis_url == "redis://localhost/1"
    with pytest.raises(ValueError, match="requires mysql_url"):
        make_settings(tmp_path, session_redis_url="redis://localhost/1")
