import asyncio
import importlib
import sys

import pytest

from app.server.core.config import StartupConfig


def _reload_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_bootstrap_module_imports_without_optional_runtime_dependencies():
    bootstrap = _reload_module("app.server.bootstrap")
    lifecycle = _reload_module("app.server.lifecycle")

    assert bootstrap is not None
    assert lifecycle is not None


def test_shutdown_scheduler_supports_sync_shutdown_api():
    bootstrap = _reload_module("app.server.bootstrap")

    class FakeScheduler:
        running = True

        def __init__(self):
            self.calls = []

        def shutdown(self, wait=False):
            self.calls.append(wait)

    scheduler = FakeScheduler()

    bootstrap.get_scheduler = lambda: scheduler

    asyncio.run(bootstrap.shutdown_scheduler())

    assert scheduler.calls == [False]


def test_shutdown_clients_does_not_reference_missing_chat_client(monkeypatch):
    bootstrap = _reload_module("app.server.bootstrap")
    calls = []

    async def _close(name):
        calls.append(name)

    monkeypatch.setattr(bootstrap, "close_eml_client", lambda: _close("eml"))
    monkeypatch.setattr(bootstrap, "close_s3_client", lambda: _close("s3"))
    monkeypatch.setattr(bootstrap, "close_embed_client", lambda: _close("embed"))
    monkeypatch.setattr(bootstrap, "close_es_client", lambda: _close("es"))
    monkeypatch.setattr(bootstrap, "close_db_client", lambda: _close("db"))

    asyncio.run(bootstrap.shutdown_clients())

    assert calls == ["eml", "s3", "embed", "es", "db"]


def test_initialize_db_connection_raises_on_db_init_failure(monkeypatch):
    bootstrap = _reload_module("app.server.bootstrap")

    async def _boom(cfg):
        raise RuntimeError("db init failed")

    monkeypatch.setattr(bootstrap, "init_db_client", _boom)

    with pytest.raises(RuntimeError, match="db init failed"):
        asyncio.run(bootstrap.initialize_db_connection(StartupConfig()))


def test_initialize_system_fails_when_required_initializer_returns_none(monkeypatch):
    lifecycle = _reload_module("app.server.lifecycle")

    async def _ok(*args, **kwargs):
        return object()

    async def _missing(*args, **kwargs):
        return None

    monkeypatch.setattr(lifecycle, "initialize_db_connection", _ok)
    monkeypatch.setattr(lifecycle, "initialize_observability", _ok)
    monkeypatch.setattr(lifecycle, "initialize_global_clients", _ok)
    monkeypatch.setattr(lifecycle, "initialize_tool_manager", _missing)
    monkeypatch.setattr(lifecycle, "initialize_skill_manager", _ok)
    monkeypatch.setattr(lifecycle, "initialize_session_manager", _ok)
    monkeypatch.setattr(lifecycle, "initialize_scheduler", _ok)

    with pytest.raises(RuntimeError, match="tool manager"):
        asyncio.run(lifecycle.initialize_system(StartupConfig()))
