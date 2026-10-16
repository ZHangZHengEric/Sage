"""Destructive operations, serialized with this host's Run admission."""
from __future__ import annotations

import asyncio

from app.v2.server.storage.workspaces import with_workspace_binding, workspace_user
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES


def busy():
    return SageV2Error(RuntimeErrorInfo(
        code="server.workspace.busy", category=ErrorCategory.CONFLICT,
        message="workspace is used by an unfinished task", retryable=True,
        metadata={"detail": "workspace_busy"},
    ))


async def require_idle(service, tenant_id: str, agent_id: str):
    """A working directory is not an access boundary: guard the whole workspace.

    Include descendant Sessions and durable dispatch intents, even when the
    thread projection is absent. Terminal Runs may still have a local drive
    unwinding tools or publishing their final thread projection.
    """
    owner = await service.runs.catalog.agent_owner(agent_id)
    if owner is None:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.agent.not_found", category=ErrorCategory.VALIDATION,
            message="Agent not found"))
    context = service.context_for(owner)
    store = service.application.entrypoint().runtime.session_store
    candidates = {entry.run.run_id for entry in await store.list_dispatchable_runs()}
    for thread in await service.threads.list_for(owner):
        try:
            sessions = [thread.thread_id]
            sessions.extend(item.session_id for item in
                            await service.session_access.list_descendant_sessions(thread.thread_id, context))
            for session in sessions:
                candidates.update(run.run_id for run in
                                  await service.session_access.list_session_runs(session, context))
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise
    for run_id in candidates:
        run = await store.get_run(run_id)
        if run.state in TERMINAL_RUN_STATES and not service.runs.execution.driving(run_id):
            continue
        command = await store.get_start_command(run_id)
        if command.agent_id != agent_id:
            continue
        command = await with_workspace_binding(command, owner, service.threads)
        # Unresolvable historical identity fails closed.
        if workspace_user(command, owner) == tenant_id:
            raise busy()


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
    async with service.runs.workspace_mutation_lock:
        owner, internal_id = await service._scope(tenant_id, agent_id, session_id)
        # Also protects callbacks that can upsert a deleted thread on completion.
        await require_idle(service, tenant_id, agent_id)
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
