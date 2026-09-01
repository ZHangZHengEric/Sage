from __future__ import annotations

import pytest

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.testing import (
    run_scheduler_conformance,
    run_session_store_recovery_conformance,
)


@pytest.mark.asyncio
async def test_reference_scheduler_passes_distributed_semantic_harness():
    scheduler = InMemoryScheduler()
    await run_scheduler_conformance(scheduler)
    await scheduler.close()


@pytest.mark.asyncio
async def test_filesystem_store_passes_outbox_and_restart_cursor_harness(tmp_path):
    context = RequestContext(
        actor=ActorRef(
            principal_id="conformance",
            principal_type=PrincipalType.SERVICE,
            tenant_id="tenant",
        )
    )
    await run_session_store_recovery_conformance(
        lambda: FilesystemSessionStore(tmp_path / "sessions"), context
    )
