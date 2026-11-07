"""PostgreSQL Server selection must be complete and reject mixed backends."""

import pytest

from app.v2.server.config.settings import ServerSettings
from app.v2.server.config.manifest import server_v2_manifest
from tests.app.v2.server.conftest import make_settings


DSN = "postgresql://sage@localhost/sage?sslmode=require"


def test_postgres_server_selects_driver_and_session_store(tmp_path):
    settings = make_settings(tmp_path, postgres_url=DSN)
    assert settings.database_url() == DSN.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    selection = server_v2_manifest(settings).runtime.capabilities["session.store"]
    assert selection.plugin == "sage.session.postgres"
    assert selection.config == {"dsn": DSN, "table_prefix": ""}


def test_postgres_environment_does_not_require_mysql(tmp_path, monkeypatch):
    monkeypatch.delenv("SAGE_SERVER_MYSQL_URL", raising=False)
    monkeypatch.setenv("SAGE_SERVER_POSTGRES_URL", DSN)
    monkeypatch.setenv("SAGE_SERVER_JWT_SECRET", "postgres-test-secret-" * 3)
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.postgres_url == DSN
    assert settings.mysql_url is None


@pytest.mark.parametrize(
    "extra",
    [
        {"mysql_url": "mysql://localhost/sage"},
        {"session_store_plugin": "sage.session.mysql"},
        {
            "session_store_plugin": "sage.session.redis-mysql",
            "redis_url": "redis://localhost/0",
        },
        {
            "session_store_plugin": "sage.session.postgres",
            "scheduler_plugin": "sage.scheduler.redis-distributed",
            "redis_url": "redis://localhost/0",
        },
    ],
)
def test_postgres_server_rejects_incompatible_backend_selections(tmp_path, extra):
    with pytest.raises(ValueError):
        make_settings(tmp_path, postgres_url=DSN, **extra)


@pytest.mark.parametrize("mode", ["direct", "redis", "distributed"])
def test_postgres_server_host_schema_login_run_and_restart(tmp_path, mode):
    import os
    from uuid import uuid4
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    from fastapi.testclient import TestClient
    from app.v2.server.bootstrap import ServerHost
    from app.v2.server.database import Database, DatabaseSettings
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import CompletingJudgeModel, scripted_hello
    from tests.app.v2.server.test_external_chat import setup_agent
    from app.v2.server.conversations.external_runs import selected_run

    dsn = os.environ.get("SAGE_V2_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_POSTGRES_DSN to run live PostgreSQL Server tests")
    import psycopg
    from psycopg import sql

    schema = "server_test_" + uuid4().hex[:12]
    parsed = urlsplit(dsn)
    options = dict(parse_qsl(parsed.query))
    options["options"] = options.get("options", "") + f" -csearch_path={schema}"
    isolated = urlunsplit(parsed._replace(query=urlencode(options)))
    redis_url = os.environ.get("SAGE_V2_TEST_REDIS_URL") if mode != "direct" else None
    if mode != "direct" and not redis_url:
        pytest.skip("set SAGE_V2_TEST_REDIS_URL for Redis/PostgreSQL Server tests")
    settings = make_settings(
        tmp_path,
        postgres_url=isolated,
        redis_url=redis_url,
        session_store_key_prefix="sage:server-test:{" + schema + "}"
        if redis_url
        else None,
        scheduler_plugin="sage.scheduler.redis-distributed"
        if mode == "distributed"
        else "sage.scheduler.ephemeral",
    )

    def host():
        return ServerHost(
            settings,
            model_provider=CompletingJudgeModel(scripted_hello()),
            database=Database(DatabaseSettings(url=settings.database_url())),
        )

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        service = host()
        with TestClient(create_app(service)) as client:
            setup_agent(client)
            agent_id = client.headers["SAGE-AGENT-ID"]
            response = client.post(
                f"/api/agents/{agent_id}/runs",
                headers={"SAGE-TENANT-ID": "pg-tenant"},
                json={
                    "threadId": "pg-thread",
                    "runId": "pg-run",
                    "messages": [{"id": "m", "role": "user", "content": "hello"}],
                },
            )
            assert response.status_code == 200, response.text
            assert "RUN_FINISHED" in response.text
        restarted = host()
        with TestClient(create_app(restarted)) as client:

            async def restore():
                details = await selected_run(
                    restarted.conversations,
                    tenant_id="pg-tenant",
                    agent_id=agent_id,
                    thread_id="pg-thread",
                    run_id="pg-run",
                )
                assert details[0]["state"] == "completed"

            client.portal.call(restore)
    finally:
        if redis_url:
            import asyncio
            from redis.asyncio import Redis
            from app.v2.server.config.manifest import distributed_runtime_prefix

            async def clean_redis():
                monitor = Redis.from_url(redis_url, decode_responses=True)
                prefixes = [
                    settings.session_store_key_prefix,
                    distributed_runtime_prefix(settings, "scheduler"),
                    distributed_runtime_prefix(settings, "jobs"),
                ]
                for prefix in prefixes:
                    keys = [key async for key in monitor.scan_iter(match=prefix + ":*")]
                    if keys:
                        await monitor.delete(*keys)
                await monitor.aclose()

            asyncio.run(clean_redis())
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.mark.parametrize("sqlstate,retries", [("40001", 1), ("40P01", 1), ("23505", 0)])
async def test_postgres_transaction_retries_only_serialization_and_deadlock(
    sqlstate, retries
):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from sqlalchemy.exc import OperationalError
    from app.v2.server.database import Database, DatabaseSettings

    class DriverFailure(Exception):
        pass

    original = DriverFailure("conflict")
    original.sqlstate = sqlstate
    failure = OperationalError("write", None, original)
    database = Database(DatabaseSettings(url="postgresql+psycopg://unused/test"))

    @asynccontextmanager
    async def transaction():
        yield object()

    database.transaction = transaction
    operation = AsyncMock(side_effect=[failure, "done"])
    sleep = AsyncMock()
    if retries:
        assert await database.run_transaction(operation, sleep=sleep) == "done"
        assert operation.await_count == 2
        sleep.assert_awaited_once()
    else:
        with pytest.raises(OperationalError) as caught:
            await database.run_transaction(operation, sleep=sleep)
        assert caught.value is failure
        assert operation.await_count == 1
        sleep.assert_not_awaited()


@pytest.mark.parametrize("explicit", [False, True])
def test_postgres_redis_server_supports_distributed_scheduling(tmp_path, explicit):
    settings = make_settings(
        tmp_path,
        postgres_url=DSN,
        redis_url="redis://localhost/0",
        session_store_plugin="sage.session.redis-postgres" if explicit else None,
        scheduler_plugin="sage.scheduler.redis-distributed",
    )
    runtime = server_v2_manifest(settings).runtime
    store = runtime.capabilities["session.store"]
    assert store.plugin == "sage.session.redis-postgres"
    assert (
        store.config["dsn"] == DSN and store.config["redis_url"] == settings.redis_url
    )
    assert (
        runtime.capabilities["execution.scheduler"].plugin
        == "sage.scheduler.redis-distributed"
    )
    assert (
        runtime.capabilities["execution.job-runtime"].plugin
        == "sage.job.redis-distributed"
    )
    assert runtime.required_guarantees["session.store"]["multi_process_writes"]
    assert runtime.required_guarantees["session.store"]["atomic_worker_fence"]


def test_postgres_redis_namespaces_keep_credentials_private_and_separate_schemas(
    tmp_path,
):
    from app.v2.server.config.manifest import distributed_runtime_prefix
    from dataclasses import replace

    settings = make_settings(
        tmp_path,
        postgres_url="postgresql://user:private@localhost/sage",
        redis_url="redis://localhost/0",
    )
    prefix = distributed_runtime_prefix(settings, "scheduler")
    assert "private" not in prefix and "user" not in prefix
    assert prefix == distributed_runtime_prefix(
        replace(settings, postgres_url="postgresql://user:changed@localhost/sage"),
        "scheduler",
    )
    assert prefix != distributed_runtime_prefix(
        replace(
            settings,
            postgres_url="postgresql://user@localhost/sage?options=-csearch_path%3Dother",
        ),
        "scheduler",
    )
