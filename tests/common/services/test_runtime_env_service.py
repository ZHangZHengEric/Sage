from __future__ import annotations

import asyncio

import pytest

from common.schemas.chat import Message, StreamRequest
from common.services import chat_service
from common.services.runtime_env_service import (
    RUNTIME_ENV_UNSET,
    RuntimeEnvStore,
    RuntimeEnvValidationError,
    validate_runtime_env_vars,
)


def test_validate_runtime_env_vars_accepts_custom_string_values():
    assert validate_runtime_env_vars(
        {
            "THIRD_PARTY_API_KEY": "secret",
            "_EMPTY_ALLOWED": "",
        }
    ) == {
        "THIRD_PARTY_API_KEY": "secret",
        "_EMPTY_ALLOWED": "",
    }


@pytest.mark.parametrize(
    "name",
    [
        "NOT-AN-ENV-NAME",
        "PATH",
        "HOME",
        "PYTHONPATH",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "SAGE_DEFAULT_LLM_API_KEY",
        "OPENSANDBOX_API_KEY",
    ],
)
def test_validate_runtime_env_vars_rejects_reserved_or_unsafe_names(name):
    with pytest.raises(RuntimeEnvValidationError):
        validate_runtime_env_vars({name: "value"})


def test_validate_runtime_env_vars_rejects_non_strings_nul_and_size_limits():
    with pytest.raises(RuntimeEnvValidationError):
        validate_runtime_env_vars({"COUNT": 3})  # type: ignore[dict-item]
    with pytest.raises(RuntimeEnvValidationError):
        validate_runtime_env_vars({"TOKEN": "before\0after"})
    with pytest.raises(RuntimeEnvValidationError):
        validate_runtime_env_vars({"TOKEN": "x" * (16 * 1024 + 1)})
    with pytest.raises(RuntimeEnvValidationError):
        validate_runtime_env_vars(
            {f"KEY_{index}": "value" for index in range(65)}
        )


@pytest.mark.asyncio
async def test_store_isolates_sessions_and_supports_replace_omit_and_clear():
    now = [100.0]
    cleaned = []

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        cleaned.append(
            (owner_id, session_id, tuple(related_session_ids), tuple(resources))
        )

    store = RuntimeEnvStore(
        ttl_seconds=1800,
        clock=lambda: now[0],
        cleanup=cleanup,
    )

    await store.reserve_run("user", "session-a")
    assert await store.resolve_for_run(
        "user", "session-a", {"TOKEN": "a"}
    ) == {"TOKEN": "a"}
    await store.finish_run("user", "session-a")

    await store.reserve_run("user", "session-b")
    assert await store.resolve_for_run(
        "user", "session-b", {"TOKEN": "b"}
    ) == {"TOKEN": "b"}
    await store.finish_run("user", "session-b")

    await store.reserve_run("user", "session-a")
    assert await store.resolve_for_run(
        "user", "session-a", RUNTIME_ENV_UNSET
    ) == {"TOKEN": "a"}
    assert await store.resolve_for_run(
        "user", "session-a", {"TOKEN": "a2"}
    ) == {"TOKEN": "a2"}
    assert await store.resolve_for_run("user", "session-a", {}) == {}
    await store.finish_run("user", "session-a")

    assert await store.get_snapshot("user", "session-a") == {}
    assert await store.get_snapshot("user", "session-b") == {"TOKEN": "b"}
    assert cleaned == []


@pytest.mark.asyncio
async def test_store_refreshes_ttl_after_run_and_does_not_expire_active_run():
    now = [100.0]
    cleaned = []

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        cleaned.append(
            (owner_id, session_id, tuple(related_session_ids), tuple(resources))
        )

    store = RuntimeEnvStore(
        ttl_seconds=1800,
        clock=lambda: now[0],
        cleanup=cleanup,
    )

    await store.reserve_run("user", "session")
    await store.resolve_for_run("user", "session", {"TOKEN": "value"})

    now[0] = 4000.0
    assert await store.expire_due() == 0
    assert await store.get_snapshot("user", "session") == {"TOKEN": "value"}

    await store.finish_run("user", "session")
    now[0] = 5799.0
    assert await store.expire_due() == 0

    now[0] = 5800.0
    assert await store.expire_due() == 1
    assert await store.get_snapshot("user", "session") == {}
    assert cleaned == [("user", "session", ("session",), ())]


@pytest.mark.asyncio
async def test_store_reaper_cleans_expired_environment_automatically():
    cleaned = asyncio.Event()

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        cleaned.set()

    store = RuntimeEnvStore(ttl_seconds=0.01, cleanup=cleanup)
    await store.start()
    try:
        await store.reserve_run("user", "session")
        await store.resolve_for_run("user", "session", {"TOKEN": "value"})
        await store.finish_run("user", "session")

        await asyncio.wait_for(cleaned.wait(), timeout=1)
        assert await store.get_snapshot("user", "session") == {}
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_expiring_one_session_does_not_clean_another_sessions_resources():
    now = [0.0]
    cleaned = []
    resource_a = object()
    resource_b = object()

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        cleaned.append(
            (owner_id, session_id, tuple(related_session_ids), tuple(resources))
        )

    store = RuntimeEnvStore(
        ttl_seconds=1800,
        clock=lambda: now[0],
        cleanup=cleanup,
    )

    for session_id, token, resource in (
        ("session-a", "a", resource_a),
        ("session-b", "b", resource_b),
    ):
        await store.reserve_run("user", session_id)
        await store.resolve_for_run("user", session_id, {"TOKEN": token})
        await store.register_resource(
            "user",
            session_id,
            resource,
            resource_session_id=f"{session_id}-child",
        )
        await store.finish_run("user", session_id)

    now[0] = 900.0
    await store.reserve_run("user", "session-b")
    await store.resolve_for_run("user", "session-b", RUNTIME_ENV_UNSET)
    await store.finish_run("user", "session-b")

    now[0] = 1800.0
    assert await store.expire_due() == 1
    assert cleaned == [
        (
            "user",
            "session-a",
            ("session-a", "session-a-child"),
            (resource_a,),
        )
    ]
    assert await store.get_snapshot("user", "session-b") == {"TOKEN": "b"}


@pytest.mark.asyncio
async def test_replacing_environment_revokes_resources_holding_old_snapshot():
    cleaned = []
    resource = object()

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        cleaned.append(
            (owner_id, session_id, tuple(related_session_ids), tuple(resources))
        )

    store = RuntimeEnvStore(cleanup=cleanup)
    await store.reserve_run("user", "session")
    await store.resolve_for_run("user", "session", {"TOKEN": "old"})
    await store.register_resource(
        "user", "session", resource, resource_session_id="session-child"
    )
    await store.finish_run("user", "session")

    await store.reserve_run("user", "session")
    assert await store.resolve_for_run("user", "session", {}) == {}

    assert cleaned == [
        (
            "user",
            "session",
            ("session", "session-child"),
            (resource,),
        )
    ]


@pytest.mark.asyncio
async def test_prepare_and_execute_chat_session_manage_runtime_env_lease(monkeypatch):
    calls = []

    class FakeStore:
        async def reserve_run(self, owner_id, session_id):
            calls.append(("reserve", owner_id, session_id))

        async def resolve_for_run(self, owner_id, session_id, update):
            calls.append(("resolve", owner_id, session_id, update))
            return {"TOKEN": "snapshot"}

        async def finish_run(self, owner_id, session_id):
            calls.append(("finish", owner_id, session_id))

    class FakeStreamService:
        def __init__(
            self,
            request,
            *,
            runtime_env_owner_id=None,
            runtime_env_vars=None,
            runtime_env_store=None,
            runtime_env_refresh=False,
        ):
            self.request = request
            self.runtime_env_owner_id = runtime_env_owner_id
            self.runtime_env_vars = runtime_env_vars
            self.runtime_env_store = runtime_env_store
            self.runtime_env_refresh = runtime_env_refresh
            self.sage_engine = None
            self._runtime_env_run_finished = False

        async def initialize_workspace_assets(self):
            return None

        async def process_stream(self):
            if False:
                yield {}

        async def finish_runtime_env_run(self):
            if self._runtime_env_run_finished:
                return
            self._runtime_env_run_finished = True
            await self.runtime_env_store.finish_run(
                self.runtime_env_owner_id, self.request.session_id
            )

    fake_store = FakeStore()
    monkeypatch.setattr(chat_service, "SageStreamService", FakeStreamService)
    monkeypatch.setattr(
        chat_service, "get_runtime_env_store", lambda: fake_store
    )
    monkeypatch.setattr(
        chat_service,
        "_finalize_session_end",
        lambda request: _async_noop(),
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        session_id="session",
        user_id="user",
    )
    service, lock = await chat_service.prepare_session(
        request,
        runtime_env_owner_id="user",
        runtime_env_update={"TOKEN": "value"},
    )

    assert service.runtime_env_vars == {"TOKEN": "snapshot"}
    assert calls[:2] == [
        ("reserve", "user", "session"),
        ("resolve", "user", "session", {"TOKEN": "value"}),
    ]

    chunks = [chunk async for chunk in chat_service.execute_chat_session(service)]
    assert any('"type": "stream_end"' in chunk for chunk in chunks)
    assert calls[-1] == ("finish", "user", "session")

    if lock.locked():
        await lock.release()


async def _async_noop():
    return None
