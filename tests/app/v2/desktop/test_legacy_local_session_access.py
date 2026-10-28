from unittest.mock import AsyncMock

import pytest

from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.session import FilesystemSessionStore


@pytest.mark.asyncio
async def test_original_local_session_history_and_usage_remain_authorized_without_rewriting_owner(tmp_path):
    root = tmp_path / "runtime"
    store = FilesystemSessionStore(root)
    original_context = RequestContext(actor=ActorRef(
        principal_id="default_user", principal_type=PrincipalType.USER,
    ))
    created = await store.create_run(StartRun(
        agent_id="sage", input=(InputItem(role="user", content=(TextBlock(text="Original conversation"),)),),
        resolved_spec_hash="sha256:original", idempotency_key="original",
    ), original_context)
    session = await store.get_session(created.handle.session_id)
    command = await store.get_start_command(created.handle.run_id)
    await store.close()
    snapshot = next((root / "sessions").rglob("state.json"))
    original_bytes = snapshot.read_bytes()
    service = DesktopV2Service(tmp_path)
    try:
        await service.session_index.upsert(session)
        value = await service.session_snapshot(session.session_id, "default_user")
        assert value["session"]["session_id"] == session.session_id
        assert len(value["runs"]) == 1
        assert service._context("default_user").actor.tenant_id is None
        assert "session.admin" not in service._context("default_user").actor.scopes
        assert await service.session_access.get_start_command(created.handle.run_id, service._context("default_user")) == command
        service.observability.list_model_requests = AsyncMock(return_value=({
            "status": "completed", "session_id": session.session_id,
            "run_id": created.handle.run_id, "started_at": utc_now().isoformat(),
            "metadata": {"agent_id": "sage"}, "request": {"model": "original"},
            "response": {"usage": {"input_tokens": 100, "output_tokens": 20}},
        },))
        usage = await service.usage_overview("default_user")
        assert usage["data_quality"]["skipped_sessions"] == 0
        assert usage["totals"]["total_tokens"] == 120
        assert usage["totals"]["sessions"] == 1
        with pytest.raises(SageV2Error) as denied:
            await service.session_snapshot(session.session_id, "another_user")
        assert denied.value.info.code == "session.actor_not_authorized"
        assert snapshot.read_bytes() == original_bytes
    finally:
        await service.close()


def test_explicit_user_contexts_keep_distinct_tenant_scopes():
    alice = DesktopV2Service._context("alice").actor
    bob = DesktopV2Service._context("bob").actor
    assert alice.tenant_id == alice.principal_id == "alice"
    assert bob.tenant_id == bob.principal_id == "bob"
