from __future__ import annotations

import pytest
import asyncio
from sqlalchemy import text

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.identity.repository import DatabaseUserStore
from tests.app.v2.server.conftest import register_and_login


@pytest.mark.parametrize(
    "secret", ["", "short", "dev-only-change-me-sage-server-jwt-secret"]
)
def test_settings_reject_missing_or_unsafe_signing_secrets(
    tmp_path, monkeypatch, secret
):
    from app.v2.server.config.settings import ServerSettings

    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@localhost/sage")
    monkeypatch.setenv("SAGE_SERVER_JWT_SECRET", secret)
    with pytest.raises(ValueError, match="SAGE_SERVER_JWT_SECRET"):
        ServerSettings.from_env(data_root=tmp_path)


def test_settings_no_longer_supply_a_default_admin_password(tmp_path, monkeypatch):
    from app.v2.server.config.settings import ServerSettings

    monkeypatch.setenv("SAGE_SERVER_MYSQL_URL", "mysql://sage@localhost/sage")
    monkeypatch.setenv(
        "SAGE_SERVER_JWT_SECRET", "tests-only-32-byte-secret-abcdef012345"
    )
    monkeypatch.delenv("SAGE_SERVER_ADMIN_PASSWORD", raising=False)
    settings = ServerSettings.from_env(data_root=tmp_path)
    assert settings.admin_password == ""
    assert settings.cookie_secure is True


def test_browser_login_rejects_foreign_origin(client):
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin12345"},
            headers={"Origin": "https://foreign.example"},
        ).status_code
        == 403
    )


def test_startup_migrates_legacy_account_before_accepting_login(tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from app.v2.server.bootstrap import ServerHost
    from app.v2.server.identity.passwords import hash_password
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import make_settings

    path = tmp_path / "startup.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE users (user_id VARCHAR(64) PRIMARY KEY, username VARCHAR(191) UNIQUE, "
            "password_hash VARCHAR(255) NOT NULL, role VARCHAR(16), execution_policy TEXT)"
        )
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (
                "legacy-admin",
                "ExistingAdmin",
                hash_password("old-password"),
                "admin",
                '{"shell":"deny"}',
            ),
        )
    # Existing administrators do not require a new bootstrap password.
    host = ServerHost(
        make_settings(tmp_path, admin_password=""),
        database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{path}")),
    )
    app = create_app(host)
    for _ in range(2):
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "existingadmin", "password": "old-password"},
            )
            assert login.status_code == 200, login.text
            user = login.json()["data"]["user"]
            assert user["user_id"] == "legacy-admin"
            assert user["role"] == "admin"
            assert user["execution_policy"]["shell"] == "deny"


def test_logout_revokes_the_presented_token(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/session", headers=headers).status_code == 401


def test_logout_does_not_revoke_another_login(client):
    first = register_and_login(client)
    second = client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret1"}
    ).json()["data"]["access_token"]
    assert (
        client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {first}"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {second}"}
        ).status_code
        == 200
    )


def test_cookie_writes_require_session_bound_csrf(client):
    register_and_login(client)
    assert client.post("/api/auth/logout").status_code == 403
    csrf = client.cookies.get("sage_server_v2_csrf")
    assert csrf
    assert (
        client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert (
        client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert client.get("/api/auth/session").status_code == 401


@pytest.mark.asyncio
async def test_legacy_accounts_migrate_without_losing_passwords_or_ids(tmp_path):
    database = Database(
        DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/legacy.db")
    )
    await database.start()
    try:
        async with database._engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE users (user_id VARCHAR(64) PRIMARY KEY, username VARCHAR(191) UNIQUE, "
                    "password_hash VARCHAR(255) NOT NULL, role VARCHAR(16))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO users VALUES ('user_old', 'Alice', 'legacy-hash', 'user')"
                )
            )
        await create_host_schema(database)
        await create_host_schema(database)
        users = DatabaseUserStore(database)
        user = await users.get_by_username(" ALICE ")
        assert user.user_id == "user_old"
        assert not hasattr(user, "password_hash")
        assert (
            await users.get_password_credential(user.user_id)
        ).password_hash == "legacy-hash"
        async with database._engine.begin() as connection:
            await connection.execute(
                text("UPDATE password_credentials SET password_hash = 'new-hash'")
            )
        await create_host_schema(database)
        assert (
            await users.get_password_credential(user.user_id)
        ).password_hash == "new-hash"
    finally:
        await database.stop()


@pytest.mark.asyncio
async def test_migration_rejects_conflicting_legacy_users_without_merging(tmp_path):
    database = Database(
        DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/conflict.db")
    )
    await database.start()
    try:
        async with database._engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE users (user_id VARCHAR(64) PRIMARY KEY, username VARCHAR(191) UNIQUE, "
                    "password_hash VARCHAR(255) NOT NULL, role VARCHAR(16), execution_policy TEXT)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO users VALUES ('a', 'Alice', 'hash-a', 'user', '{}'), "
                    "('b', 'ALICE', 'hash-b', 'user', '{}')"
                )
            )
        for _ in range(2):
            with pytest.raises(ValueError, match="Conflicting normalized usernames"):
                await create_host_schema(database)
        async with database._engine.connect() as connection:
            assert (
                await connection.execute(
                    text("SELECT user_id, password_hash FROM users ORDER BY user_id")
                )
            ).all() == [("a", "hash-a"), ("b", "hash-b")]
    finally:
        await database.stop()


@pytest.mark.asyncio
async def test_concurrent_schema_startup_is_safe(tmp_path):
    database = Database(
        DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/concurrent.db")
    )
    await database.start()
    try:
        await asyncio.gather(create_host_schema(database), create_host_schema(database))
        await asyncio.gather(create_host_schema(database), create_host_schema(database))
    finally:
        await database.stop()


@pytest.mark.asyncio
async def test_sessions_and_revocations_survive_service_recreation(service):
    from app.v2.server.identity.sessions import DatabaseLoginSessionStore, LoginSessions
    from sagents.v2.contracts.errors import SageV2Error

    await service.start()
    try:
        user = await service.identity.register("durable-user", "secret1")
        token, _ = await service.identity.issue_token(user)
        another = LoginSessions(
            DatabaseLoginSessionStore(service.database),
            secret=service.settings.jwt_secret,
            expire_hours=1,
        )
        assert (await another.authenticate(token)).user_id == user.user_id
        await another.revoke(token)
        with pytest.raises(SageV2Error):
            await service.identity.from_token(token)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_parallel_registration_is_atomic_and_case_insensitive(tmp_path):
    from app.v2.server.identity.local import LocalPasswordAuth
    from sagents.v2.contracts.errors import SageV2Error

    database = Database(
        DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/registration.db")
    )
    await database.start()
    await create_host_schema(database)
    users = DatabaseUserStore(database)
    auth = LocalPasswordAuth(users)
    try:
        results = await asyncio.gather(
            auth.create("Alice", "secret1"),
            auth.create("ALICE", "secret2"),
            return_exceptions=True,
        )
        assert sum(isinstance(item, SageV2Error) for item in results) == 1
        assert len(await users.list_users()) == 1
        user = await users.get_by_username("alice")
        assert await users.get_password_credential(user.user_id) is not None
    finally:
        await auth.close()
        await database.stop()


@pytest.mark.asyncio
async def test_parallel_admin_bootstrap_returns_the_same_account(tmp_path):
    from app.v2.server.identity.local import LocalPasswordAuth

    database = Database(
        DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/admin.db")
    )
    await database.start()
    await create_host_schema(database)
    auth = LocalPasswordAuth(DatabaseUserStore(database))
    try:
        first, second = await asyncio.gather(
            auth.ensure_admin("admin", "secret1"), auth.ensure_admin("admin", "secret1")
        )
        assert first.user_id == second.user_id
        assert len(await auth.users.list_users()) == 1
    finally:
        await auth.close()
        await database.stop()


@pytest.mark.asyncio
async def test_bootstrap_never_promotes_an_existing_ordinary_user(service):
    from sagents.v2.contracts.errors import SageV2Error

    user = await service.identity.register("admin", "secret1")
    try:
        with pytest.raises(SageV2Error):
            await service.identity.ensure_admin("admin", "different-secret")
        assert (await service.users.get_by_id(user.user_id)).role == "user"
    finally:
        await service.identity.close()


@pytest.mark.asyncio
async def test_external_identity_is_explicit_and_does_not_require_password(service):
    from app.v2.server.identity.users import build_user_record
    from sagents.v2.contracts.errors import SageV2Error

    await service.start()
    try:
        user = build_user_record("sso-user")
        await service.users.create(user)
        await service.identity.external.bind(
            "https://id.example", "subject-A", user.user_id
        )
        assert (
            await service.identity.external.resolve("https://id.example", "subject-A")
        ).user_id == user.user_id
        assert (
            await service.identity.external.resolve("https://id.example", "subject-a")
            is None
        )
        assert (
            await service.identity.external.resolve(
                "https://other.example", "subject-A"
            )
            is None
        )
        with pytest.raises(SageV2Error):
            await service.identity.authenticate("sso-user", "anything")
        other = await service.identity.register("other-user", "secret1")
        with pytest.raises(SageV2Error):
            await service.identity.external.bind(
                "https://id.example", "subject-A", other.user_id
            )
    finally:
        await service.close()
