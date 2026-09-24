from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sagents.v2.contracts.items import UsageSummary
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep

from app.server_v2.main import create_app
from app.server_v2.core.settings import ServerSettings
from app.server_v2.bootstrap import HostRepositories, ServerHost
from app.server_v2.infrastructure.database import Database, DatabaseSettings
from app.server_v2.infrastructure.persistence import MemoryApiKeyStore
from tests.app.server_v2.fakes import (
    MemoryCatalogStore,
    MemorySkillStore,
    MemoryThreadIndex,
    MemoryUserStore,
)


class FixtureServerHost(ServerHost):
    """Start the test database for direct host tests; TestClient starts it itself."""

    async def start(self) -> None:
        self._started_test_database = not await self.database.ready()
        if self._started_test_database:
            await self.database.start()
        try:
            await super().start()
        except BaseException:
            if self._started_test_database:
                await self.database.stop()
                self._started_test_database = False
            raise

    async def close(self) -> None:
        await super().close()
        if getattr(self, "_started_test_database", False):
            await self.database.stop()
            self._started_test_database = False


def make_settings(tmp_path: Path, **overrides) -> ServerSettings:
    values = {
        "host": "127.0.0.1",
        "port": 8090,
        "data_root": tmp_path,
        "jwt_secret": "test-secret-test-secret-test-secret",
        "jwt_expire_hours": 1,
        "language": "zh",
        "admin_username": "admin",
        "admin_password": "admin12345",
    }
    values.update(overrides)
    return ServerSettings(**values)


def scripted_hello(steps: int = 1) -> ScriptedModelProvider:
    return ScriptedModelProvider(
        tuple(
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="hello"),
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id=f"response_{index + 1}",
                            text="hello",
                            finish_reason="stop",
                            usage=UsageSummary(input_tokens=3, output_tokens=1),
                        ),
                    ),
                )
            )
            for index in range(steps)
        )
    )


def make_test_service(
    tmp_path: Path,
    *,
    model_provider=None,
    fallback=True,
    **overrides,
) -> ServerHost:
    settings = make_settings(tmp_path, **overrides)
    provider = model_provider
    if provider is None and fallback:
        provider = scripted_hello()
    return FixtureServerHost(
        settings,
        model_provider=provider,
        database=Database(
            DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")
        ),
        repositories=HostRepositories(
            users=MemoryUserStore(),
            catalog=MemoryCatalogStore(),
            threads=MemoryThreadIndex(),
            skills=MemorySkillStore(),
            api_keys=MemoryApiKeyStore(),
        ),
    )


@pytest.fixture
def service(tmp_path: Path) -> ServerHost:
    return make_test_service(tmp_path)


@pytest.fixture
def client(service: ServerHost):
    with TestClient(create_app(service=service)) as test_client:
        yield test_client


def register_and_login(client: TestClient, username: str = "alice") -> str:
    created = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret1"},
    )
    assert created.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret1"},
    )
    assert login.status_code == 200
    return login.json()["data"]["access_token"]
