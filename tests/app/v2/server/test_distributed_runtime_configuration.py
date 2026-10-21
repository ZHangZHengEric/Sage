"""Host declaration contracts for independent storage and scheduler selection.

Exercise settings, manifest selection and the real builtin plugin inventory;
no server application or external database is needed for configuration rules.
"""

from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.contracts.principals import PrincipalType
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep

from sagents.v2.package.manifest.runtime import CapabilitySelection

import pytest

from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.config.settings import ServerSettings
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from tests.app.v2.server.conftest import make_settings


REDIS_STORE = "sage.session.redis-mysql"


def test_distributed_selection_pairs_store_scheduler_and_required_guarantees(tmp_path):
    settings = make_settings(
        tmp_path, mysql_url="mysql://unused/test", redis_url="redis://unused/0",
        session_store_plugin=REDIS_STORE, scheduler_plugin="sage.scheduler.redis-distributed",
    )
    runtime = server_v2_manifest(settings).runtime
    store = runtime.capabilities["session.store"]
    scheduler = runtime.capabilities["execution.scheduler"]
    jobs = runtime.capabilities["execution.job-runtime"]
    assert cast(CapabilitySelection, store).plugin == REDIS_STORE
    assert cast(CapabilitySelection, store).config["dsn"] == settings.mysql_url
    assert cast(CapabilitySelection, store).config["redis_url"] == settings.redis_url
    assert cast(CapabilitySelection, scheduler).plugin == "sage.scheduler.redis-distributed"
    assert cast(CapabilitySelection, scheduler).config["redis_url"] == settings.redis_url
    assert cast(CapabilitySelection, scheduler).config["lease_seconds"] == 30
    assert cast(CapabilitySelection, scheduler).config["max_concurrent_runs"] == settings.max_concurrent_runs
    assert cast(CapabilitySelection, scheduler).config["max_concurrent_runs_per_tenant"] == settings.max_concurrent_runs_per_user
    assert runtime.required_guarantees["session.store"]["multi_process_writes"] is True
    assert runtime.required_guarantees["session.store"]["cross_process_subscribe"] is True
    assert runtime.required_guarantees["execution.scheduler"]["supports_distributed_claims"] is True
    assert cast(CapabilitySelection, jobs).plugin == "sage.job.redis-distributed"
    assert cast(CapabilitySelection, jobs).config["redis_url"] == cast(CapabilitySelection, store).config["redis_url"]
    assert cast(CapabilitySelection, jobs).config["key_prefix"] != cast(CapabilitySelection, scheduler).config["key_prefix"]
    assert runtime.required_guarantees["execution.job-runtime"] == {
        "multi_process_writes": True, "supports_remote_cancel": True}


@pytest.mark.parametrize("mysql_url,redis_url", [(None, None), ("mysql://unused/test", None)])
def test_distributed_selection_requires_mysql_and_redis(tmp_path, mysql_url, redis_url):
    with pytest.raises(ValueError):
        settings = make_settings(
            tmp_path, mysql_url=mysql_url, redis_url=redis_url,
            session_store_plugin=REDIS_STORE, scheduler_plugin="sage.scheduler.redis-distributed")
        server_v2_manifest(settings)


@pytest.mark.parametrize("redis_url,expected", [(None, "sage.session.mysql"), ("redis://unused/0", "sage.session.redis-mysql")])
def test_default_selection_preserves_existing_store_and_scheduler(tmp_path, redis_url, expected):
    settings = make_settings(tmp_path, mysql_url="mysql://unused/test", redis_url=redis_url)
    assert settings.session_store_plugin is None
    runtime = server_v2_manifest(settings).runtime
    assert cast(CapabilitySelection, runtime.capabilities["session.store"]).plugin == expected
    assert cast(CapabilitySelection, runtime.capabilities["execution.scheduler"]).plugin == "sage.scheduler.ephemeral"
    assert "execution.job-runtime" not in runtime.required_guarantees
    assert runtime.required_guarantees["session.store"].get("multi_process_writes", False) is bool(redis_url)


def test_environment_selects_storage_and_scheduler_independently(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://unused/test")
    monkeypatch.setenv("SAGE_SERVER_REDIS_URL", "redis://unused/0")
    monkeypatch.setenv("SAGE_SERVER_SESSION_STORE_PLUGIN", REDIS_STORE)
    monkeypatch.setenv("SAGE_SERVER_SCHEDULER_PLUGIN", "sage.scheduler.redis-distributed")
    monkeypatch.setenv("SAGE_SERVER_SESSION_STORE_KEY_PREFIX", "existing-session-namespace")
    monkeypatch.setenv("SAGE_SERVER_SCHEDULER_PLUGIN", "sage.scheduler.redis-distributed")
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.session_store_plugin == REDIS_STORE
    runtime = server_v2_manifest(settings).runtime
    assert cast(CapabilitySelection, runtime.capabilities["execution.scheduler"]).plugin == "sage.scheduler.redis-distributed"
    assert cast(CapabilitySelection, runtime.capabilities["session.store"]).config["key_prefix"] == "existing-session-namespace"
    assert cast(CapabilitySelection, server_v2_manifest(settings).runtime.capabilities["session.store"]).plugin == REDIS_STORE


def test_distributed_plugins_keep_independent_public_ids_names_and_capabilities():
    inventory = {entry["plugin_id"]: entry for entry in builtin_extension_registry().inventory()}
    for old_id, new_id in (
        ("sage.session.mysql", REDIS_STORE),
        ("sage.scheduler.ephemeral", "sage.scheduler.redis-distributed"),
    ):
        old, new = inventory[old_id], inventory[new_id]
        assert old["name"] != new["name"]
        assert old["capabilities"]["multi_process_writes"] is False
        assert new["capabilities"]["multi_process_writes"] is True
    assert inventory[REDIS_STORE]["capabilities"]["cross_process_subscribe"] is True
    assert inventory["sage.session.mysql"]["capabilities"]["cross_process_subscribe"] is False
    assert inventory["sage.job.redis-distributed"]["name"] != inventory["sage.job.ephemeral"]["name"]
    assert inventory["sage.job.redis-distributed"]["capabilities"]["supports_remote_cancel"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("store_plugin,scheduler_plugin,scheduler_url,jobs_plugin,expected_error", [
    (REDIS_STORE, "sage.scheduler.redis-distributed", "redis://unused/0", "sage.job.redis-distributed", None),
    (REDIS_STORE, "sage.scheduler.ephemeral", None, "sage.job.ephemeral", None),
    ("sage.session.ephemeral", "sage.scheduler.redis-distributed", "redis://unused/0", "sage.job.redis-distributed", "runtime.distributed_fence_unsupported"),
    (REDIS_STORE, "sage.scheduler.redis-distributed", "redis://other/0", "sage.job.redis-distributed", "runtime.distributed_redis_mismatch"),
    (REDIS_STORE, "sage.scheduler.redis-distributed", "redis://unused/0", "sage.job.ephemeral", "runtime.capability_guarantee_unsatisfied"),
])
async def test_real_builder_selects_plugins_and_rejects_unsafe_pairs(
    tmp_path, monkeypatch, store_plugin, scheduler_plugin, scheduler_url, jobs_plugin, expected_error
):
    import fakeredis
    import fakeredis.aioredis
    from unittest.mock import AsyncMock
    from redis.asyncio import Redis
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.sdk_fixture import build_registered_app
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.package.manifest.runtime import RuntimeConfig, CapabilitySelection

    server = fakeredis.FakeServer()

    def client(*args, **kwargs):
        value = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
        value.info = AsyncMock(return_value={"maxmemory_policy": "noeviction", "aof_enabled": 1})
        return value

    monkeypatch.setattr(Redis, "from_url", client)
    runtime = RuntimeConfig(state_root=str(tmp_path), start_workers=False,
        required_guarantees={"execution.job-runtime": {"multi_process_writes": True, "supports_remote_cancel": True}}
        if scheduler_plugin == "sage.scheduler.redis-distributed" else {}, capabilities={
        "session.store": CapabilitySelection(plugin=store_plugin,
            config={"dsn": "mysql://unused/test", "redis_url": "redis://unused/0"} if store_plugin == REDIS_STORE else {}),
        "execution.scheduler": CapabilitySelection(plugin=scheduler_plugin,
            config={"redis_url": scheduler_url} if scheduler_url else {}),
        "execution.job-runtime": CapabilitySelection(plugin=jobs_plugin,
            config={"redis_url": "redis://unused/0"} if jobs_plugin == "sage.job.redis-distributed" else {}),
    })
    if expected_error:
        with pytest.raises(SageV2Error) as rejected:
            await build_registered_app(tmp_path, runtime=runtime, model=ScriptedModelProvider(cast('tuple[ScriptedModelStep, ...]', [])))
        assert rejected.value.info.code == expected_error
    else:
        app = await build_registered_app(tmp_path, runtime=runtime, model=ScriptedModelProvider(cast('tuple[ScriptedModelStep, ...]', [])))
        try:
            assert app.service("session.store").plugin_id == store_plugin
            assert app.service("execution.scheduler").plugin_id == scheduler_plugin
            assert app.service("execution.job-runtime").plugin_id == jobs_plugin
            facts = await app.service("execution.job-runtime").capabilities()
            assert facts.multi_process_writes is (jobs_plugin == "sage.job.redis-distributed")
            assert facts.supports_remote_cancel is (jobs_plugin == "sage.job.redis-distributed")
            dispatcher = app.service("execution.dispatcher")
            assert dispatcher.distributed_claims is (scheduler_plugin == "sage.scheduler.redis-distributed")
            if dispatcher.distributed_claims:
                assert dispatcher.lease_duration.total_seconds() == 30
        finally:
            await app.close()


@pytest.mark.parametrize("config", [
    {"session_store_plugin": "sage.session.redis-mysql-distributed"},
    {"scheduler_plugin": "unknown.scheduler"},
    {"scheduler_plugin": "sage.scheduler.redis-distributed", "redis_url": None},
    {"scheduler_plugin": "sage.scheduler.redis-distributed", "session_store_plugin": "sage.session.mysql"},
    {"session_store_key_prefix": "existing", "session_store_plugin": "sage.session.mysql"},
])
def test_removed_or_incompatible_deployment_selections_are_rejected(tmp_path, config):
    values: dict[str, Any] = {"mysql_url": "mysql://unused/test", "redis_url": "redis://unused/0", **config}
    with pytest.raises(ValueError):
        make_settings(tmp_path, **values)


@pytest.mark.parametrize("scheduler_plugin", ["sage.scheduler.ephemeral", "sage.scheduler.redis-distributed"])
async def test_managed_apps_isolate_explicit_redis_namespaces_and_validation_stays_local(
    service, tmp_path, scheduler_plugin
):
    """An explicit Server prefix must not merge two managed Apps' Redis state."""
    from dataclasses import replace
    from sagents.v2 import AgentPackageBundle
    from sagents.v2.contracts.principals import ActorRef, RequestContext

    await service.start()
    try:
        user = await service.identity.register("namespace-owner", "secret1")
        context = RequestContext(actor=ActorRef(
            principal_id=user.user_id, principal_type=cast('PrincipalType', "user"), tenant_id=user.user_id,
        ))
        management = service.agent_management
        bundle = AgentPackageBundle.model_validate(await management.queries.template(context))
        factory = management.package_builder_factory
        factory.settings = replace(factory.settings,
            mysql_url="mysql://unused/test", redis_url="redis://unused/0",
            session_store_key_prefix="existing-server", scheduler_plugin=scheduler_plugin)
        first = await factory.build(bundle, tmp_path / "managed-a", context, management)
        second = await factory.build(bundle, tmp_path / "managed-b", context, management)
        validation = await factory.build(bundle, tmp_path / "validate-a", context, management)
        first_store = first.runtime.capabilities["session.store"]
        second_store = second.runtime.capabilities["session.store"]
        assert first_store.plugin == second_store.plugin == REDIS_STORE
        assert first_store.config["table_prefix"] != second_store.config["table_prefix"]
        assert first_store.config["key_prefix"] != second_store.config["key_prefix"]
        assert first_store.config["key_prefix"].startswith("existing-server:")
        if scheduler_plugin == "sage.scheduler.redis-distributed":
            first_scheduler = first.runtime.capabilities["execution.scheduler"]
            second_scheduler = second.runtime.capabilities["execution.scheduler"]
            assert first_scheduler.plugin == second_scheduler.plugin == scheduler_plugin
            assert first_scheduler.config["queue_id"] != second_scheduler.config["queue_id"]
        assert validation.runtime.capabilities["session.store"].plugin == "sage.session.filesystem"
        assert validation.runtime.capabilities["execution.scheduler"].plugin != "sage.scheduler.redis-distributed"
    finally:
        await service.close()
