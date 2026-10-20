"""Host declaration contracts for explicit distributed runtime selection.

Exercise settings, manifest selection and the real builtin plugin inventory;
no server application or external database is needed for configuration rules.
"""

import pytest

from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.config.settings import ServerSettings
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from tests.app.v2.server.conftest import make_settings


DISTRIBUTED_STORE = "sage.session.redis-mysql-distributed"


def test_distributed_selection_pairs_store_scheduler_and_required_guarantees(tmp_path):
    settings = make_settings(
        tmp_path, mysql_url="mysql://unused/test", redis_url="redis://unused/0",
        session_store_plugin=DISTRIBUTED_STORE,
    )
    runtime = server_v2_manifest(settings).runtime
    store = runtime.capabilities["session.store"]
    scheduler = runtime.capabilities["execution.scheduler"]
    assert store.plugin == DISTRIBUTED_STORE
    assert store.config["dsn"] == settings.mysql_url
    assert store.config["redis_url"] == settings.redis_url
    assert scheduler.plugin == "sage.scheduler.redis-distributed"
    assert scheduler.config["redis_url"] == settings.redis_url
    assert scheduler.config["lease_seconds"] == 30
    assert scheduler.config["max_concurrent_runs"] == settings.max_concurrent_runs
    assert scheduler.config["max_concurrent_runs_per_tenant"] == settings.max_concurrent_runs_per_user
    assert runtime.required_guarantees["session.store"]["multi_process_writes"] is True
    assert runtime.required_guarantees["session.store"]["cross_process_subscribe"] is True
    assert runtime.required_guarantees["execution.scheduler"]["supports_distributed_claims"] is True


@pytest.mark.parametrize("mysql_url,redis_url", [(None, None), ("mysql://unused/test", None)])
def test_distributed_selection_requires_mysql_and_redis(tmp_path, mysql_url, redis_url):
    with pytest.raises(ValueError):
        settings = make_settings(
            tmp_path, mysql_url=mysql_url, redis_url=redis_url,
            session_store_plugin=DISTRIBUTED_STORE)
        server_v2_manifest(settings)


@pytest.mark.parametrize("redis_url,expected", [(None, "sage.session.mysql"), ("redis://unused/0", "sage.session.redis-mysql")])
def test_default_selection_preserves_existing_store_and_scheduler(tmp_path, redis_url, expected):
    settings = make_settings(tmp_path, mysql_url="mysql://unused/test", redis_url=redis_url)
    assert settings.session_store_plugin is None
    runtime = server_v2_manifest(settings).runtime
    assert runtime.capabilities["session.store"].plugin == expected
    assert runtime.capabilities["execution.scheduler"].plugin == "sage.scheduler.ephemeral"
    assert not runtime.required_guarantees["session.store"].get("multi_process_writes", False)


def test_environment_can_explicitly_select_the_distributed_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://unused/test")
    monkeypatch.setenv("SAGE_SERVER_REDIS_URL", "redis://unused/0")
    monkeypatch.setenv("SAGE_SERVER_SESSION_STORE_PLUGIN", DISTRIBUTED_STORE)
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.session_store_plugin == DISTRIBUTED_STORE
    assert server_v2_manifest(settings).runtime.capabilities["session.store"].plugin == DISTRIBUTED_STORE


def test_distributed_plugins_keep_independent_public_ids_names_and_capabilities():
    inventory = {entry["plugin_id"]: entry for entry in builtin_extension_registry().inventory()}
    for old_id, new_id in (
        ("sage.session.redis-mysql", DISTRIBUTED_STORE),
        ("sage.scheduler.ephemeral", "sage.scheduler.redis-distributed"),
    ):
        old, new = inventory[old_id], inventory[new_id]
        assert old["name"] != new["name"]
        assert old["capabilities"]["multi_process_writes"] is False
        assert new["capabilities"]["multi_process_writes"] is True
    assert inventory[DISTRIBUTED_STORE]["capabilities"]["cross_process_subscribe"] is True
    assert inventory["sage.session.redis-mysql"]["capabilities"]["cross_process_subscribe"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("store_plugin,scheduler_plugin,scheduler_url,expected_error", [
    (DISTRIBUTED_STORE, "sage.scheduler.redis-distributed", "redis://unused/0", None),
    (DISTRIBUTED_STORE, "sage.scheduler.ephemeral", None, "runtime.distributed_fence_unsupported"),
    ("sage.session.redis-mysql", "sage.scheduler.redis-distributed", "redis://unused/0", "runtime.distributed_fence_unsupported"),
    (DISTRIBUTED_STORE, "sage.scheduler.redis-distributed", "redis://other/0", "runtime.distributed_redis_mismatch"),
])
async def test_real_builder_selects_plugins_and_rejects_unsafe_pairs(
    tmp_path, monkeypatch, store_plugin, scheduler_plugin, scheduler_url, expected_error
):
    import fakeredis
    import fakeredis.aioredis
    from unittest.mock import AsyncMock
    from redis.asyncio import Redis
    from sagents.v2 import SAgentBuilder
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.package.manifest.runtime import RuntimeConfig, CapabilitySelection

    server = fakeredis.FakeServer()

    def client(*args, **kwargs):
        value = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
        value.info = AsyncMock(return_value={"maxmemory_policy": "noeviction", "aof_enabled": 1})
        return value

    monkeypatch.setattr(Redis, "from_url", client)
    runtime = RuntimeConfig(state_root=str(tmp_path), start_workers=False, capabilities={
        "session.store": CapabilitySelection(plugin=store_plugin,
            config={"dsn": "mysql://unused/test", "redis_url": "redis://unused/0"}),
        "execution.scheduler": CapabilitySelection(plugin=scheduler_plugin,
            config={"redis_url": scheduler_url} if scheduler_url else {}),
    })
    if expected_error:
        with pytest.raises(SageV2Error) as rejected:
            await SAgentBuilder().build(runtime=runtime)
        assert rejected.value.info.code == expected_error
    else:
        app = await SAgentBuilder().build(runtime=runtime)
        try:
            assert app.service("session.store").plugin_id == store_plugin
            assert app.service("execution.scheduler").plugin_id == scheduler_plugin
            dispatcher = app.service("execution.dispatcher")
            assert dispatcher.distributed_claims
            assert dispatcher.lease_duration.total_seconds() == 30
        finally:
            await app.close()
