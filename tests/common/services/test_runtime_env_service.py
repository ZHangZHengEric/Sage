from __future__ import annotations

import pytest

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

    async def cleanup(owner_id, session_id, resources):
        cleaned.append((owner_id, session_id, tuple(resources)))

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

    async def cleanup(owner_id, session_id, resources):
        cleaned.append((owner_id, session_id, tuple(resources)))

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
    assert cleaned == [("user", "session", ())]


@pytest.mark.asyncio
async def test_expiring_one_session_does_not_clean_another_sessions_resources():
    now = [0.0]
    cleaned = []
    resource_a = object()
    resource_b = object()

    async def cleanup(owner_id, session_id, resources):
        cleaned.append((owner_id, session_id, tuple(resources)))

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
        await store.register_resource("user", session_id, resource)
        await store.finish_run("user", session_id)

    now[0] = 900.0
    await store.reserve_run("user", "session-b")
    await store.resolve_for_run("user", "session-b", RUNTIME_ENV_UNSET)
    await store.finish_run("user", "session-b")

    now[0] = 1800.0
    assert await store.expire_due() == 1
    assert cleaned == [("user", "session-a", (resource_a,))]
    assert await store.get_snapshot("user", "session-b") == {"TOKEN": "b"}
