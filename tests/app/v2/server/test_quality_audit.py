"""Server ownership and frozen inputs through standard registered execution."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.errors import SageV2Error
from app.v2.server.identity.users import UserRecord
from app.v2.server.catalog.records import require_agent
from app.v2.server.runtime.models import create_catalog_provider
from contextvars import ContextVar
from app.v2.server.conversations.composition import composition_metadata, load_composition
from app.v2.server.runtime.loop import load_catalog_agent
from tests.app.v2.server.conftest import make_test_service, scripted_hello
from tests.app.v2.server.test_models import _save_demo_model
from tests.app.v2.server.test_skill_runtime import _command


async def execute(host, command, owner):
    loaded = await load_catalog_agent(host, command, owner)
    command = command.model_copy(update={"agent_id": loaded.id, "resolved_spec_hash": loaded.composition_hash})
    stream = await host.application.entrypoint().run_stream(command, host.contexts.for_user(owner), agent=loaded)
    events = [event async for event in stream.events]
    result = await stream.wait()
    assert result.state.value == "completed", events
    return result


@pytest.mark.asyncio
async def test_registered_models_follow_authorized_run_not_stale_worker_context(tmp_path, monkeypatch):
    host = make_test_service(tmp_path, fallback=False)
    owners = []
    def provider(record):
        owners.append(record.model)
        from tests.app.v2.server.conftest import CompletingJudgeModel
        return CompletingJudgeModel(scripted_hello())
    monkeypatch.setattr("app.v2.server.runtime.models._build_catalog_provider", provider)
    await host.start()
    try:
        for owner in ("alice", "bob"):
            await host.users.save(UserRecord(user_id=owner, username=owner, password_hash="unused"))
            await host.catalog.upsert_model(owner, {"model": owner, "api_key": "test", "is_default": True})
        worker_identity = ContextVar("unrelated_worker_identity")
        token = worker_identity.set("unrelated-worker")
        try:
            for owner in ("alice", "bob"):
                agent = require_agent(await host.catalog.get(owner), (await host.catalog.get(owner)).default_agent_id)
                command = _command().model_copy(update={"agent_id": agent.id, "idempotency_key": owner,
                    "config": RunConfig(enabled_skills=(), metadata=composition_metadata(agent=agent, skills=(), mcp_servers=()))})
                result = await execute(host, command, owner)
                with pytest.raises(SageV2Error):
                    await host.application.agent_for_run(result.run_id, host.contexts.for_user("other"))
        finally:
            worker_identity.reset(token)
        assert set(owners) == {"alice", "bob"}
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_loading_standard_revision_does_not_open_inference_client(tmp_path, monkeypatch):
    host = make_test_service(tmp_path, fallback=False)
    opened = []
    monkeypatch.setattr("app.v2.server.runtime.models._build_catalog_provider", lambda record: opened.append(record))
    await host.start()
    try:
        await host.users.save(UserRecord(user_id="user", username="user", password_hash="unused"))
        await _save_demo_model(host.catalog, "user")
        agent = (await host.catalog.get("user")).default_agent_id
        loaded = await load_catalog_agent(host, _command().model_copy(update={"agent_id": agent}), "user")
        assert loaded.composition_hash
        assert opened == []
    finally:
        await host.close()
    assert opened == []


@pytest.mark.asyncio
async def test_registered_run_uses_original_agent_and_skill_version(tmp_path, monkeypatch):
    host = make_test_service(tmp_path)
    await host.start()
    observed = []
    from app.v2.server.runtime import sdk_plugins
    original = sdk_plugins.run_inputs
    async def capture(*args):
        values = await original(*args)
        observed.append(values[2])
        return values
    monkeypatch.setattr(sdk_plugins, "run_inputs", capture)
    try:
        await host.users.save(UserRecord(user_id="user", username="user", password_hash="unused"))
        catalog = await host.catalog.get("user")
        admitted = require_agent(catalog, catalog.default_agent_id).with_configuration(instructions="Admitted instructions")
        first = await host.skill_catalog.publish_markdown(name="demo",
            content="---\nname: demo\ndescription: First\n---\n\n# First\n", user_id="user", role="user")
        await host.skill_catalog.bind_agent_skills(owner_user_id="user", agent_id=admitted.id, names=["demo"])
        records = tuple(await host.skill_catalog.bound_skills(owner_user_id="user", agent_id=admitted.id))
        command = _command().model_copy(update={"agent_id": admitted.id, "config": RunConfig(
            enabled_skills=("demo",), metadata=composition_metadata(agent=admitted, skills=records, mcp_servers=()))})
        await host.skill_catalog.update_content(first.skill_id,
            "---\nname: demo\ndescription: Second\n---\n\n# Second\n", user_id="user", role="user")
        await host.skill_catalog.bind_agent_skills(owner_user_id="user", agent_id=admitted.id, names=[])
        catalog.agents[0] = catalog.agents[0].with_configuration(instructions="Edited afterwards")
        await host.catalog_store.save("user", catalog)
        await execute(host, command, "user")
        assert observed
        assert all(value.agent.instructions == "Admitted instructions" for value in observed)
        assert all(value.skills[0].version_id == first.version_id for value in observed)
    finally:
        await host.close()


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
