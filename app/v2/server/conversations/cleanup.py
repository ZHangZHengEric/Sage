"""Destructive operations, serialized with this host's Run admission."""
from __future__ import annotations

import asyncio

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def busy():
    return SageV2Error(RuntimeErrorInfo(
        code="server.workspace.busy", category=ErrorCategory.CONFLICT,
        message="workspace is used by an unfinished task", retryable=True,
        metadata={"detail": "workspace_busy"},
    ))


def reject_local_workspace_drive(service, tenant_id: str, agent_id: str):
    # Terminal state is published before product completion callbacks settle.
    # Keep those callbacks inside the same workspace lifetime as the driver.
    if service.runs.execution.workspace_driving(tenant_id, agent_id):
        raise busy()


async def require_idle(service, tenant_id: str, agent_id: str, *, owner_id: str):
    """Probe only verified roots for this physical workspace and their children."""
    reject_local_workspace_drive(service, tenant_id, agent_id)
    store = service.application.runtime.session_store
    cursor = None
    while True:
        page = await service.threads.workspace_session_page(
            tenant_id, agent_id, owner_id=owner_id, cursor=cursor, limit=200)
        session_ids = list(page.session_ids)
        from app.v2.server.storage.workspaces import workspace_user, workspace_agent_id
        for session_id in page.legacy_session_ids:
            try:
                command = await service.session_access.latest_session_start_command(
                    session_id, service.context_for(owner_id))
            except SageV2Error as exc:
                if exc.info.code.endswith("not_found"):
                    continue
                raise
            if command is not None and workspace_agent_id(command) == agent_id and workspace_user(command, owner_id) == tenant_id:
                session_ids.append(session_id)
        if session_ids and await store.has_nonterminal_session_trees(session_ids):
            raise busy()
        cursor = page.next_cursor
        if cursor is None:
            return


async def finish_file_operation(function, *args, **kwargs):
    """Do not release the admission lock while a cancelled worker still deletes."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


async def delete_external_session(service, tenant_id, agent_id, session_id):
    reject_local_workspace_drive(service, tenant_id, agent_id)
    async with service.runs.workspace_guard(tenant_id, agent_id):
        owner, internal_id = await service._scope(tenant_id, agent_id, session_id)
        # Also protects callbacks that can upsert a deleted thread on completion.
        await require_idle(service, tenant_id, agent_id, owner_id=owner)
        context = service.context_for(owner)
        try:
            await service.session_access.delete_session(internal_id, context)
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise
        record = await service.threads.find(internal_id)
        if record is not None:
            await service.threads.remove(internal_id, owner)
        return internal_id
