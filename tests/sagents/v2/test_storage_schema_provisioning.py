"""Externally managed storage can start without provisioning its schema."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext, ProviderSet
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.session.plugins.mysql import state as mysql_state
from sagents.v2.runtime.session.plugins.postgres import state as postgres_state


def create_plugin(plugin_id, config):
    registry = builtin_extension_registry()
    registry.validate_parameters(plugin_id, config)
    return registry.get(plugin_id).factory(
        ExtensionScopeContext(
            scope=ExtensionScope.PROCESS, scope_id="storage", config=config
        ),
        ProviderSet(),
    )


@pytest.mark.parametrize("backend", ["mysql", "postgres"])
@pytest.mark.parametrize("redis", [False, True])
@pytest.mark.parametrize("external_schema", [False, True])
async def test_sql_startup_can_skip_schema_provisioning(
    monkeypatch, backend, redis, external_schema
):
    config = {"dsn": f"{backend}://unused/test"}
    if redis:
        config["redis_url"] = "redis://unused/0"
    if external_schema:
        config["provision_schema"] = False
    prefix = "redis-" if redis else ""
    store = create_plugin(f"sage.session.{prefix}{backend}", config)
    coordinator = store._coordinator
    state = coordinator._archive if redis else coordinator
    connection = SimpleNamespace(set_isolation_level=AsyncMock())
    checkout = MagicMock()
    checkout.return_value.__aenter__.return_value = connection
    bootstrap = AsyncMock(return_value=())

    if backend == "mysql":
        pool = SimpleNamespace(
            acquire=checkout, close=MagicMock(), wait_closed=AsyncMock()
        )
        driver = SimpleNamespace(create_pool=AsyncMock(return_value=pool))
        monkeypatch.setattr(mysql_state, "_require_aiomysql", lambda: driver)
        monkeypatch.setattr(state, "_bootstrap", bootstrap)
    else:
        pool = SimpleNamespace(connection=checkout, open=AsyncMock(), close=AsyncMock())
        isolation = SimpleNamespace(READ_COMMITTED=1, REPEATABLE_READ=2)
        monkeypatch.setitem(
            sys.modules, "psycopg", SimpleNamespace(IsolationLevel=isolation)
        )
        monkeypatch.setitem(
            sys.modules,
            "psycopg_pool",
            SimpleNamespace(AsyncConnectionPool=MagicMock(return_value=pool)),
        )
        monkeypatch.setattr(postgres_state, "bootstrap", bootstrap)

    try:
        await state._ensure_ready()
        checkout.assert_called_once_with()
        if external_schema:
            bootstrap.assert_not_awaited()
            connection.set_isolation_level.assert_not_awaited()
        elif backend == "postgres":
            bootstrap.assert_awaited_once_with(state, connection)
            assert connection.set_isolation_level.await_args_list == [
                call(isolation.READ_COMMITTED), call(isolation.REPEATABLE_READ)
            ]
        else:
            bootstrap.assert_awaited_once_with(connection)
    finally:
        await state.close()
