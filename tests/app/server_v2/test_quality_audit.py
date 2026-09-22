from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.skill.plugins.session import SessionDerivedSkillActivationRepository
from sagents.v2.tool.plugins.ephemeral import EphemeralToolPlugin

from app.server_v2.services.models import (
    HostModelProvider,
    bind_model_user,
    create_catalog_provider,
    reset_model_user,
)
from app.server_v2.services.skill_runtime import (
    CatalogRunDriver,
    _skill_snapshot,
    compose_catalog_loop,
    skill_snapshot_metadata,
)
from tests.app.server_v2.conftest import make_test_service, scripted_hello
from tests.app.server_v2.fakes import MemoryCatalogStore
from tests.app.server_v2.test_models import _save_demo_model
from tests.app.server_v2.test_skill_runtime import _command


async def _attach_without_host_sandbox(*args, **kwargs):
    del args, kwargs
    return EphemeralToolPlugin(), None, None


@pytest.mark.asyncio
async def test_run_owner_overrides_stale_worker_context_and_unknown_run_is_not_guessed():
    catalog = MemoryCatalogStore()

    async def lookup(run):
        return "session-b" if run == "run-b" else None

    model = HostModelProvider(catalog, session_for_run=lookup)
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
async def test_cancelled_sdk_construction_closes_result_and_stays_off_event_loop():
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

    task = asyncio.create_task(
        create_catalog_provider(SimpleNamespace(to_provider=create))
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
async def test_dynamic_model_is_closed_after_run_or_composition_failure(
    tmp_path, monkeypatch, fail_materialization
):
    service = make_test_service(tmp_path)
    await service.start()
    await _save_demo_model(service.catalog, "user")
    provider = scripted_hello()
    closed = []

    async def close():
        closed.append(True)

    monkeypatch.setattr(provider, "close", close, raising=False)
    monkeypatch.setattr(
        "app.server_v2.domain.catalog.ModelRecord.to_provider", lambda self: provider
    )
    if fail_materialization:

        async def fail(*args, **kwargs):
            raise ValueError("materialization failed")

        monkeypatch.setattr(service.application, "materialize_agent", fail)
    try:
        if fail_materialization:
            with pytest.raises(ValueError, match="materialization failed"):
                await compose_catalog_loop(service, _command(), user_id="user")
        else:
            _, ports = await compose_catalog_loop(service, _command(), user_id="user")
            driver = CatalogRunDriver(service, "run")
            driver._ports = ports
            await driver._close_ports()
            await driver._close_ports()
        assert closed == []
        assert (await service._host_models._pool.snapshot())["active_leases"] == 0
    finally:
        await service.close()
    assert closed == [True]


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
    driver._ports = SimpleNamespace(scope_handles=tuple(Resource(i) for i in range(3)))
    with pytest.raises(ValueError, match="close failed"):
        await driver._close_ports()
    assert closed == [2, 1, 0]
    await driver._close_ports()


@pytest.mark.asyncio
async def test_catalog_loop_uses_materialized_skill_plugin_and_derived_activations(
    tmp_path, monkeypatch
):
    service = make_test_service(tmp_path)
    await service.start()
    await service.skill_catalog.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
        user_id="user",
        role="user",
    )
    await service.skill_catalog.bind_agent_skills(
        owner_user_id="user", agent_id="main", names=["demo"]
    )
    captured = {}
    original = AgentCompositionFactory.create_skill_loader

    def capture(self, *args, **kwargs):
        captured.update(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentCompositionFactory, "create_skill_loader", capture)

    monkeypatch.setattr(
        "app.server_v2.services.skill_runtime.attach_official_tools",
        _attach_without_host_sandbox,
    )
    try:
        _, ports = await compose_catalog_loop(service, _command(), user_id="user")
        assert captured["skill_loading"] is ports.skill_loading
        assert isinstance(
            captured["activations"], SessionDerivedSkillActivationRepository
        )
        driver = CatalogRunDriver(service, "run")
        driver._ports = ports
        await driver._close_ports()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_catalog_loop_uses_the_skill_versions_accepted_with_the_run(
    tmp_path, monkeypatch
):
    service = make_test_service(tmp_path)
    await service.start()
    first = await service.skill_catalog.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: First\n---\n\n# First\n",
        user_id="user",
        role="user",
    )
    await service.skill_catalog.bind_agent_skills(
        owner_user_id="user", agent_id="main", names=["demo"]
    )
    accepted = tuple(
        await service.skill_catalog.bound_skills(owner_user_id="user", agent_id="main")
    )
    command = _command().model_copy(
        update={
            "config": RunConfig(
                enabled_skills=("demo",),
                metadata=skill_snapshot_metadata(accepted),
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
        owner_user_id="user", agent_id="main", names=[]
    )
    captured = {}
    original = AgentCompositionFactory.create_skill_loader

    def capture(self, *args, **kwargs):
        captured["catalog"] = kwargs["catalog"]
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentCompositionFactory, "create_skill_loader", capture)
    monkeypatch.setattr(
        "app.server_v2.services.skill_runtime.attach_official_tools",
        _attach_without_host_sandbox,
    )
    try:
        _, ports = await compose_catalog_loop(service, command, user_id="user")
        descriptor = await captured["catalog"].get_skill("demo", run_id="run")
        assert descriptor.version == first.version_id
        assert descriptor.version != second.version_id
        driver = CatalogRunDriver(service, "run")
        driver._ports = ports
        await driver._close_ports()
    finally:
        await service.close()


def test_skill_snapshot_rejects_a_user_skill_owned_by_another_tenant():
    command = _command().model_copy(
        update={
            "config": RunConfig(
                enabled_skills=("demo",),
                metadata={
                    "server_v2.skill_snapshot": [
                        {
                            "skill_id": "skill_1",
                            "version_id": "version_1",
                            "revision": 1,
                            "dimension": "user",
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
                    ]
                },
            )
        }
    )

    with pytest.raises(SageV2Error) as caught:
        _skill_snapshot(command, user_id="user")

    assert caught.value.info.code == "skill.snapshot_invalid"
