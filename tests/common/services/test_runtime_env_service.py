from __future__ import annotations

import asyncio

import pytest

from common.schemas.chat import Message, StreamRequest
from common.services import chat_service
from common.services.runtime_env_service import (
    RUNTIME_ENV_UNSET,
    RuntimeEnvRevokingError,
    RuntimeEnvStore,
    RuntimeEnvValidationError,
    _cleanup_runtime_resources,
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
async def test_register_resource_during_revoke_cleans_late_resource():
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleaned = []

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        cleaned.append(
            (owner_id, session_id, tuple(related_session_ids), tuple(resources))
        )
        if resources == ("existing",):
            cleanup_started.set()
            await allow_cleanup.wait()

    store = RuntimeEnvStore(cleanup=cleanup)
    await store.reserve_run("user", "session")
    await store.resolve_for_run("user", "session", {"TOKEN": "value"})
    await store.register_resource(
        "user", "session", "existing", resource_session_id="session-child"
    )

    revoke_task = asyncio.create_task(store.clear_session("user", "session"))
    await cleanup_started.wait()

    with pytest.raises(RuntimeEnvRevokingError):
        await store.register_resource(
            "user",
            "session",
            "late",
            resource_session_id="session-late-child",
        )

    allow_cleanup.set()
    assert await revoke_task is True
    assert cleaned == [
        (
            "user",
            "session",
            ("session", "session-child"),
            ("existing",),
        ),
        (
            "user",
            "session",
            ("session", "session-late-child"),
            ("late",),
        ),
    ]


@pytest.mark.asyncio
async def test_finish_runtime_env_run_survives_caller_cancellation():
    finish_started = asyncio.Event()
    allow_finish = asyncio.Event()
    finish_completed = asyncio.Event()

    class FakeStore:
        async def finish_run(self, owner_id, session_id):
            assert (owner_id, session_id) == ("user", "session")
            finish_started.set()
            await allow_finish.wait()
            finish_completed.set()

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        session_id="session",
        user_id="user",
    )
    service = chat_service.SageStreamService.__new__(
        chat_service.SageStreamService
    )
    service.request = request
    service.runtime_env_owner_id = "user"
    service.runtime_env_vars = {"TOKEN": "value"}
    service.runtime_env_store = FakeStore()
    service._runtime_env_run_finished = False
    service._runtime_env_finish_task = None

    finish_task = asyncio.create_task(service.finish_runtime_env_run())
    await finish_started.wait()
    finish_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finish_task

    allow_finish.set()
    await asyncio.wait_for(finish_completed.wait(), timeout=1)
    await service.finish_runtime_env_run()


@pytest.mark.asyncio
async def test_prepare_session_releases_runtime_env_lease_when_cancelled(monkeypatch):
    calls = []

    class FakeStore:
        async def reserve_run(self, owner_id, session_id):
            calls.append(("reserve", owner_id, session_id))

        async def finish_run(self, owner_id, session_id):
            calls.append(("finish", owner_id, session_id))

    fake_store = FakeStore()
    monkeypatch.setattr(
        chat_service, "get_runtime_env_store", lambda: fake_store
    )

    async def cancel_wait_for(awaitable, *, timeout):
        del timeout
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "wait_for", cancel_wait_for)
    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        session_id="cancelled-session",
        user_id="user",
    )

    with pytest.raises(asyncio.CancelledError):
        await chat_service.prepare_session(
            request,
            runtime_env_owner_id="user",
            runtime_env_update={"TOKEN": "value"},
        )

    assert calls == [
        ("reserve", "user", "cancelled-session"),
        ("finish", "user", "cancelled-session"),
    ]


@pytest.mark.asyncio
async def test_cleanup_attempts_every_resource_and_clears_all_runtime_copies(
    monkeypatch,
):
    calls = []

    class FailingResource:
        async def kill(self):
            calls.append("failing")
            raise RuntimeError("cleanup failed")

    class HealthyResource:
        async def kill(self):
            calls.append("healthy")

    failing = FailingResource()
    healthy = HealthyResource()

    class Context:
        sandbox = failing
        runtime_env_vars = {"TOKEN": "context"}
        runtime_resource_registrar = object()

    class Session:
        session_context = Context()
        runtime_env_vars = {"TOKEN": "session"}
        runtime_resource_registrar = object()

    session = Session()

    class Manager:
        def get_live_session(self, session_id):
            assert session_id == "session"
            return session

    async def cleanup_background_tasks(session_id):
        calls.append(f"background:{session_id}")

    monkeypatch.setattr(
        "sagents.session_runtime.get_global_session_manager",
        lambda: Manager(),
    )
    monkeypatch.setattr(
        "sagents.tool.impl.execute_command_tool.ExecuteCommandTool."
        "cleanup_session_background_tasks",
        cleanup_background_tasks,
    )

    with pytest.raises(RuntimeError, match="1 runtime resource cleanup"):
        await _cleanup_runtime_resources(
            "user",
            "session",
            ("session",),
            (failing, healthy),
        )

    assert calls == ["background:session", "failing", "healthy"]
    assert session.session_context.sandbox is None
    assert session.session_context.runtime_env_vars == {}
    assert session.session_context.runtime_resource_registrar is None
    assert session.runtime_env_vars == {}
    assert session.runtime_resource_registrar is None


@pytest.mark.asyncio
async def test_shutdown_retries_transient_cleanup_failure():
    attempts = 0

    async def cleanup(owner_id, session_id, related_session_ids, resources):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")

    store = RuntimeEnvStore(cleanup=cleanup)
    await store.reserve_run("user", "session")
    await store.resolve_for_run("user", "session", {"TOKEN": "value"})
    await store.finish_run("user", "session")

    await store.shutdown()

    assert attempts == 2
    assert await store.get_snapshot("user", "session") == {}


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
