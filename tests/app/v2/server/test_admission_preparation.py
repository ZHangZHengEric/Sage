"""Admission overlaps independent reads while retaining ownership and pinned configuration."""

import asyncio
from types import SimpleNamespace

from app.v2.server.conversations.admission import RunAdmission
from app.v2.server.conversations.records import ThreadRecord
from app.v2.server.runtime.policy import ExecutionPolicy
from tests.app.v2.server.fakes import MemoryCatalogStore


async def test_admission_overlaps_reads_and_uses_pinned_agent_without_full_catalog():
    catalog = MemoryCatalogStore()
    stored = await catalog.get("alice")
    pinned = stored.default_agent_id
    groups = {name: (set(), asyncio.Event()) for name in ("scope", "catalog", "skills")}

    async def meet(group, name, value):
        arrived, ready = groups[group]
        arrived.add(name)
        if len(arrived) == 2:
            ready.set()
        await ready.wait()
        return value

    read_catalog = catalog.get_for_run
    async def scoped(user_id, agent_id):
        assert agent_id == pinned
        return await meet("catalog", "catalog", await read_catalog(user_id, agent_id))

    async def full_read(_):
        raise AssertionError("admission must not load full catalog")

    catalog.get_for_run = scoped
    catalog.get = full_read
    admission = RunAdmission(
        threads=SimpleNamespace(
            find=lambda _: meet("scope", "thread", ThreadRecord(thread_id="thread", user_id="alice", agent_id=pinned)),
            binding=lambda _: meet("scope", "binding", None)),
        catalog=catalog,
        skills=SimpleNamespace(bound_skills=lambda **_: meet("skills", "skills", [])),
        users=SimpleNamespace(get_by_id=lambda _: meet("skills", "user", SimpleNamespace(execution_policy=ExecutionPolicy(shell="ask")))),
        execution=SimpleNamespace(has_model=lambda _: True),
        session_access=SimpleNamespace(list_session_runs=lambda *_: meet("catalog", "ownership", ())),
        context_for=lambda _: None,
    )
    admitted = await asyncio.wait_for(admission.prepare(
        user_id="alice", session_id="thread", agent_id="picker-was-changed", pin_existing=True,
    ), timeout=1)
    assert admitted.agent_id == pinned
    assert admitted.metadata["server_v2.execution"]["policy"]["shell"] == "ask"
    assert all(ready.is_set() for _, ready in groups.values())


def test_real_chat_never_reloads_full_catalog_after_initialization(tmp_path):
    from unittest.mock import AsyncMock, patch
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import register_and_login
    from tests.app.v2.server.test_external_chat import make_host
    from tests.app.v2.server.test_agui_chat import _run_input

    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        token = register_and_login(client)
        user = client.portal.call(host.users.get_by_username, "alice")
        client.portal.call(host.catalog_store.get, user.user_id)
        with patch.object(host.catalog_store, "get", AsyncMock(side_effect=AssertionError("full catalog read"))) as full_read:
            response = client.post("/api/agent", json=_run_input(),
                                   headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert '"type":"RUN_FINISHED"' in response.text
        assert '"type":"RUN_ERROR"' not in response.text
        full_read.assert_not_awaited()
