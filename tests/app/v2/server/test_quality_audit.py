from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from app.v2.server.identity.users import UserRecord
from app.v2.server.packages.builder import PackageBuilder

from app.v2.server.catalog.records import require_agent
from app.v2.server.runtime.models import (
    HostModelProvider,
    bind_model_user,
    create_catalog_provider,
    reset_model_user,
)
from app.v2.server.conversations.composition import composition_metadata, load_composition
from app.v2.server.runtime.driver import CatalogRunDriver
from app.v2.server.runtime.loop import compose_catalog_loop
from tests.app.v2.server.conftest import make_test_service, scripted_hello
from tests.app.v2.server.fakes import MemoryCatalogStore
from tests.app.v2.server.test_models import _save_demo_model
from tests.app.v2.server.test_skill_runtime import _command


@pytest.mark.asyncio
async def test_run_owner_overrides_stale_worker_context_and_unknown_run_is_not_guessed():
    catalog = MemoryCatalogStore()

    async def get_run(run):
        if run == "run-b":
            return SimpleNamespace(session_id="session-b")
        raise SageV2Error(
            RuntimeErrorInfo(
                code="session.run_missing",
                category=ErrorCategory.VALIDATION,
                message="run missing",
            )
        )

    model = HostModelProvider(catalog, session_store=SimpleNamespace(get_run=get_run))
    model.bind_session_user("session-b", "user-b")
    token = bind_model_user("user-a")
    try:
        assert await model._user_id("run-b") == "user-b"
        assert await model._user_id("unknown-run") is None
        with pytest.raises(SageV2Error, match="configure a model"):
            async with model._borrow("unknown-run"):
                pass
    finally:
        reset_model_user(token)
        await model.close()


@pytest.mark.asyncio
async def test_overlapping_session_bindings_are_not_removed_by_first_completion():
    model = HostModelProvider(MemoryCatalogStore())
    model.bind_session_user("session", "user")
    model.bind_session_user("session", "user")
    with pytest.raises(ValueError, match="another user"):
        model.bind_session_user("session", "other")
    model.unbind_session_user("session")
    assert model._session_users == {"session": "user"}
    model.unbind_session_user("session")
    assert not model._session_users
    assert not model._session_bindings
    await model.close()


@pytest.mark.asyncio
async def test_cancelled_sdk_construction_closes_result_and_stays_off_event_loop(monkeypatch):
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    main_thread = threading.get_ident()
    closed = []

    class Provider:
        async def close(self):
            closed.append(True)

    def create():
        assert threading.get_ident() != main_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return Provider()

    monkeypatch.setattr(
        "app.v2.server.runtime.models._build_catalog_provider",
        lambda record: create(),
    )
    task = asyncio.create_task(
        create_catalog_provider(SimpleNamespace())
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_materialization", [False, True])
async def test_package_composition_never_opens_an_inference_client(
    tmp_path, monkeypatch, fail_materialization
):
    service = make_test_service(tmp_path)
    await service.start()
    await service.users.save(UserRecord(user_id="user", username="user", password_hash="unused"))
    agent_id = (await service.catalog.get("user")).default_agent_id
    await _save_demo_model(service.catalog, "user")
    provider = scripted_hello()
    closed = []

    async def close():
        closed.append(True)

    monkeypatch.setattr(provider, "close", close, raising=False)
    monkeypatch.setattr(
        "app.v2.server.runtime.models._build_catalog_provider", lambda record: provider
    )
    if fail_materialization:

        async def fail(*args, **kwargs):
            raise ValueError("materialization failed")

        monkeypatch.setattr(PackageBuilder, "build", fail)
    try:
        if fail_materialization:
            with pytest.raises(ValueError, match="materialization failed"):
                await compose_catalog_loop(service, _command().model_copy(update={"agent_id": agent_id}), user_id="user")
        else:
            _, ports = await compose_catalog_loop(service, _command().model_copy(update={"agent_id": agent_id}), user_id="user")
            driver = CatalogRunDriver(service, "run")
            driver._resources = ports
            await driver._close_resources()
            await driver._close_resources()
        assert closed == []
        assert (await service.execution.model_pool.pool.snapshot())["active_leases"] == 0
    finally:
        await service.close()
    # Building a Package no longer opens an inference client.
    assert closed == []


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_skip_other_run_resources():
    closed = []

    class Resource:
        def __init__(self, index):
            self.index = index

        async def close(self):
            closed.append(self.index)
            if self.index == 2:
                raise ValueError("close failed")

    driver = CatalogRunDriver(None, "run")
    from sagents.v2.composition.resources import RunResources
    driver._resources = RunResources()
    for i in range(3):
        driver._resources.own(Resource(i))
    with pytest.raises(ValueError, match="close failed"):
        await driver._close_resources()
    assert closed == [2, 1, 0]
    with pytest.raises(ValueError, match="close failed"):
        await driver._close_resources()
    assert closed == [2, 1, 0, 2]


@pytest.mark.asyncio
async def test_catalog_loop_uses_materialized_skill_plugin_and_derived_activations(
    tmp_path, monkeypatch
):
    service = make_test_service(tmp_path)
    await service.start()
    await service.users.save(UserRecord(user_id="user", username="user", password_hash="unused"))
    agent_id = (await service.catalog.get("user")).default_agent_id
    await service.skill_catalog.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
        user_id="user",
        role="user",
    )
    await service.skill_catalog.bind_agent_skills(
        owner_user_id="user", agent_id=agent_id, names=["demo"]
    )
    captured = {}
    original = PackageBuilder.with_skill_provider

    def capture(self, catalog, source, workspace):
        captured["catalog"] = catalog
        return original(self, catalog, source, workspace)

    monkeypatch.setattr(PackageBuilder, "with_skill_provider", capture)

    try:
        _, ports = await compose_catalog_loop(service, _command().model_copy(update={"agent_id": agent_id}), user_id="user")
        app = ports.services[0]
        assert app.service("skill.loading").plugin_id == "sage.skill.loading.lazy"
        assert (await captured["catalog"].get_skill("demo", run_id="run")).name == "demo"
        driver = CatalogRunDriver(service, "run")
        driver._resources = ports
        await driver._close_resources()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_catalog_loop_uses_the_skill_versions_accepted_with_the_run(
    tmp_path, monkeypatch
):
    service = make_test_service(tmp_path)
    await service.start()
    await service.users.save(UserRecord(user_id="user", username="user", password_hash="unused"))
    agent_id = (await service.catalog.get("user")).default_agent_id
    first = await service.skill_catalog.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: First\n---\n\n# First\n",
        user_id="user",
        role="user",
    )
    await service.skill_catalog.bind_agent_skills(
        owner_user_id="user", agent_id=agent_id, names=["demo"]
    )
    accepted = tuple(
        await service.skill_catalog.bound_skills(owner_user_id="user", agent_id=agent_id)
    )
    command = _command().model_copy(
        update={
            "agent_id": agent_id,
            "config": RunConfig(
                enabled_skills=("demo",),
                metadata=composition_metadata(
                    agent=require_agent(await service.catalog.store.get("user"), agent_id),
                    skills=accepted,
                    mcp_servers=(),
                ),
            )
        }
    )
    second = await service.skill_catalog.update_content(
        first.skill_id,
        "---\nname: demo\ndescription: Second\n---\n\n# Second\n",
        user_id="user",
        role="user",
    )
    await service.skill_catalog.bind_agent_skills(
        owner_user_id="user", agent_id=agent_id, names=[]
    )
    captured = {}
    original = PackageBuilder.with_skill_provider

    def capture(self, catalog, source, workspace):
        captured["catalog"] = catalog
        return original(self, catalog, source, workspace)

    monkeypatch.setattr(PackageBuilder, "with_skill_provider", capture)
    try:
        _, ports = await compose_catalog_loop(service, command, user_id="user")
        descriptor = await captured["catalog"].get_skill("demo", run_id="run")
        assert descriptor.version == first.version_id
        assert descriptor.version != second.version_id
        driver = CatalogRunDriver(service, "run")
        driver._resources = ports
        await driver._close_resources()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_catalog_loop_uses_the_agent_config_accepted_with_the_run(
    tmp_path, monkeypatch
):
    service = make_test_service(tmp_path)
    await service.start()
    await service.users.save(UserRecord(user_id="user", username="user", password_hash="unused"))
    agent_id = (await service.catalog.get("user")).default_agent_id
    catalog = await service.catalog.store.get("user")
    admitted = require_agent(catalog, agent_id).with_configuration(instructions="Admitted instructions")
    command = _command().model_copy(
        update={
            "agent_id": agent_id,
            "config": RunConfig(
                enabled_skills=(),
                metadata=composition_metadata(
                    agent=admitted, skills=(), mcp_servers=()
                ),
            )
        }
    )
    catalog.agents[0] = catalog.agents[0].with_configuration(instructions="Edited after the Run was admitted")
    await service.catalog.store.save("user", catalog)
    captured = {}
    original = PackageBuilder.build

    async def capture(self, manifest, **kwargs):
        captured["instructions"] = manifest.agents[agent_id].instructions.inline
        return await original(self, manifest, **kwargs)

    monkeypatch.setattr(PackageBuilder, "build", capture)
    try:
        _, ports = await compose_catalog_loop(service, command, user_id="user")
        assert captured["instructions"] == "Admitted instructions"
        driver = CatalogRunDriver(service, "run")
        driver._resources = ports
        await driver._close_resources()
    finally:
        await service.close()


def test_run_composition_rejects_a_user_skill_owned_by_another_tenant():
    agent_id = "main"
    command = _command().model_copy(
        update={
            "agent_id": agent_id,
            "config": RunConfig(
                enabled_skills=("demo",),
                metadata={
                    "server_v2.composition": {
                        "agent": {"id": "main", "name": "Main Assistant"},
                        "mcp_servers": [],
                        "skills": [
                            {
                                "skill_id": "skill_1",
                                "version_id": "version_1",
                                "revision": 1,
                                "owner_user_id": "other-user",
                                "name": "demo",
                                "description": "Demo",
                                "artifact_path": "users/other-user/demo/version_1",
                                "skill_md_sha256": "sha256:skill",
                                "package_sha256": "sha256:package",
                                "file_count": 1,
                                "total_bytes": 1,
                                "status": "active",
                            }
                        ],
                    }
                },
            )
        }
    )

    with pytest.raises(SageV2Error) as caught:
        load_composition(command, user_id="user")

    assert caught.value.info.code == "run.composition_invalid"
