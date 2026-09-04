from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sagents.v2.agent.policy.approval_memory import (
    RememberedApproval,
    SessionApprovalMemory,
)
from sagents.v2.agent.policy.tool_policy import ApprovalMatcher
from sagents.v2.runtime.session import InMemoryDerivedStateStore


NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def matcher(name: str = "write_value", fingerprint: str = "sha256:a") -> ApprovalMatcher:
    return ApprovalMatcher(tool_name=name, fingerprint=fingerprint, summary=f"{name} …")


def approval(value: ApprovalMatcher, scope: str = "session") -> RememberedApproval:
    return RememberedApproval(
        matcher=value, scope=scope, remembered_at=NOW, remembered_by="user_1"
    )


@pytest.mark.asyncio
async def test_remember_lookup_list_and_forget_are_session_scoped():
    store = InMemoryDerivedStateStore()
    memory = SessionApprovalMemory(store)
    assert await memory.lookup(session_id="s1", matcher=matcher()) is None

    await memory.remember(session_id="s1", approval=approval(matcher()))
    await memory.remember(
        session_id="s1", approval=approval(matcher(fingerprint="sha256:b"))
    )

    assert await memory.lookup(session_id="s1", matcher=matcher()) == approval(
        matcher()
    )
    # 记忆不跨 Session。
    assert await memory.lookup(session_id="s2", matcher=matcher()) is None
    assert [
        value.matcher.fingerprint
        for value in await memory.list_remembered(session_id="s1")
    ] == ["sha256:a", "sha256:b"]

    assert await memory.forget(session_id="s1", matcher=matcher()) == 1
    assert await memory.forget(session_id="s1", matcher=matcher()) == 0
    assert await memory.lookup(session_id="s1", matcher=matcher()) is None
    assert await memory.forget(session_id="s1") == 1
    assert await memory.list_remembered(session_id="s1") == ()
    assert (
        await store.get_derived_state(
            "s1", SessionApprovalMemory.NAMESPACE, SessionApprovalMemory.KEY
        )
        is None
    )


@pytest.mark.asyncio
async def test_remember_is_idempotent_and_requires_an_exact_matcher():
    memory = SessionApprovalMemory(InMemoryDerivedStateStore())
    await memory.remember(session_id="s1", approval=approval(matcher()))
    await memory.remember(session_id="s1", approval=approval(matcher()))

    assert len(await memory.list_remembered(session_id="s1")) == 1
    assert (
        await memory.lookup(session_id="s1", matcher=matcher(name="read_value"))
        is None
    )
    drifted = ApprovalMatcher(
        tool_name="write_value", fingerprint="sha256:a", summary="different text"
    )
    # 同 key 但匹配器不完全一致：宁可多问一次，也不放行。
    assert await memory.lookup(session_id="s1", matcher=drifted) is None


@pytest.mark.asyncio
async def test_unsupported_scope_is_rejected_instead_of_widened():
    memory = SessionApprovalMemory(InMemoryDerivedStateStore())
    with pytest.raises(ValueError, match="workspace"):
        await memory.remember(
            session_id="s1", approval=approval(matcher(), scope="workspace")
        )
    assert await memory.list_remembered(session_id="s1") == ()


@pytest.mark.asyncio
async def test_unknown_version_or_corrupt_state_is_ignored_not_trusted():
    store = InMemoryDerivedStateStore()
    memory = SessionApprovalMemory(store)
    await store.put_derived_state(
        "s1",
        SessionApprovalMemory.NAMESPACE,
        SessionApprovalMemory.KEY,
        {
            "version": 99,
            "entries": {matcher().key: approval(matcher()).model_dump(mode="json")},
        },
    )
    assert await memory.lookup(session_id="s1", matcher=matcher()) is None

    await store.put_derived_state(
        "s1", SessionApprovalMemory.NAMESPACE, SessionApprovalMemory.KEY, "garbage"
    )
    assert await memory.list_remembered(session_id="s1") == ()
    # 损坏的值会被下一次写入覆盖掉。
    await memory.remember(session_id="s1", approval=approval(matcher()))
    assert len(await memory.list_remembered(session_id="s1")) == 1


@pytest.mark.asyncio
async def test_forget_session_clears_the_memory_with_the_session():
    store = InMemoryDerivedStateStore()
    memory = SessionApprovalMemory(store)
    await memory.remember(session_id="s1", approval=approval(matcher()))
    await memory.remember(session_id="s2", approval=approval(matcher()))

    await store.forget_session("s1")

    assert await memory.lookup(session_id="s1", matcher=matcher()) is None
    assert await memory.lookup(session_id="s2", matcher=matcher()) is not None


def test_composition_identity_is_stable():
    assert SessionApprovalMemory(InMemoryDerivedStateStore()).composition_identity() == {
        "provider": "session-approval-memory",
        "scopes": ["session"],
        "version": 1,
    }
