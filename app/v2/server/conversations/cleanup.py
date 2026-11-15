"""Destructive operations, serialized with this host's Run admission."""
from __future__ import annotations

import asyncio
from anyio import CancelScope

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
    async for session_ids in workspace_session_pages(service, tenant_id, agent_id, owner_id=owner_id):
        if session_ids and await store.has_nonterminal_session_trees(session_ids):
            raise busy()


async def workspace_session_pages(service, tenant_id, agent_id, *, owner_id, claim_legacy=False):
    from app.v2.server.conversations.bindings import SessionBinding
    from app.v2.server.storage.workspaces import workspace_user, workspace_agent_id

    context = service.context_for(owner_id) if claim_legacy else None
    cursor = None
    while True:
        page = await service.threads.workspace_session_page(
            tenant_id, agent_id, owner_id=owner_id, cursor=cursor, limit=200)
        session_ids = list(page.session_ids)
        for session_id in page.legacy_session_ids:
            try:
                command = await service.session_access.latest_session_start_command(
                    session_id, context or service.context_for(owner_id))
                if (command is None or workspace_agent_id(command) != agent_id
                        or workspace_user(command, owner_id) != tenant_id):
                    continue
            except SageV2Error as exc:
                if exc.info.code.endswith("not_found") or (claim_legacy and exc.info.code == "server.workspace.identity_missing"):
                    continue
                raise
            if claim_legacy:
                async for old in _session_commands(service.session_access, session_id, context):
                    if workspace_agent_id(old) != agent_id or workspace_user(old, owner_id) != tenant_id:
                        raise RuntimeError("legacy Session has conflicting workspace identities")
                # Keep verified legacy identity available after canonical deletion,
                # even if the request fails before removing the thread projection.
                await service.threads.bind(SessionBinding(session_id, owner_id, tenant_id, agent_id))
            session_ids.append(session_id)
        yield session_ids
        cursor = page.next_cursor
        if cursor is None:
            return


async def _session_commands(access, session_id, context):
    after = None
    while True:
        runs = await access.run_metadata_page([session_id], context, after=after, limit=200)
        for run in runs:
            yield await access.get_start_command(run.run_id, context)
        if len(runs) < 200:
            return
        last = runs[-1]
        after = (last.session_id, last.created_at.isoformat(), last.run_id)


async def delete_tenant_data(host, service, tenant_id, agent_id, *, owner_id):
    reject_local_workspace_drive(service, tenant_id, agent_id)
    async with service.runs.workspace_guard(tenant_id, agent_id):
        reject_local_workspace_drive(service, tenant_id, agent_id)
        await _finish_operation(_purge_workspace_data(host, service, tenant_id, agent_id, owner_id))


async def _purge_workspace_data(host, service, tenant_id, agent_id, owner_id):
    from app.v2.server.storage.external_workspaces import clear_workspace
    from sagents.v2.memory.identity import command_memory_scope, MEMORY_IDENTITY_KEY

    store = service.application.runtime.session_store
    context = service.context_for(owner_id)
    roots, present_roots, private_memory = set(), set(), set()
    access = service.session_access
    async for ids in workspace_session_pages(
            service, tenant_id, agent_id, owner_id=owner_id, claim_legacy=True):
        if ids and await store.has_nonterminal_session_trees(ids):
            raise busy()
        roots.update(ids)
        for root in ids:
            try:
                descendants = await access.list_descendant_sessions(root, context)
            except SageV2Error as exc:
                if exc.info.code.endswith("not_found"):
                    continue
                raise
            present_roots.add(root)
            for session_id in (root, *(item.session_id for item in descendants)):
                async for command in _session_commands(access, session_id, context):
                    if MEMORY_IDENTITY_KEY in command.config.metadata:
                        scope = command_memory_scope(command, context)
                        if (scope.principal_id == tenant_id and scope.workspace_id
                                and scope.workspace_id.startswith("private:")):
                            private_memory.add(scope)

    provider = service.application.service("memory.provider")
    forget_workspace = getattr(provider, "forget_workspace", None)
    if not callable(forget_workspace):
        raise RuntimeError("configured memory provider cannot purge a workspace")
    await forget_workspace(context.actor.tenant_id, tenant_id, agent_id,
                           private_scopes=private_memory)
    await finish_file_operation(clear_workspace, host.paths, tenant_id, agent_id)
    if host.workspace_storage is not None:
        await finish_file_operation(host.workspace_storage.clear_workspace, tenant_id, agent_id)
    for root in sorted(roots):
        if root in present_roots:
            await access.delete_session(root, context, require_derived_cleanup=True)
        else:
            # An earlier session deletion may have acknowledged the canonical
            # delete but left that Session's searchable projection behind.
            await service.application.service("session-memory.provider").forget_session(root)
    finish_deletions = getattr(store, "finish_session_deletions", None)
    if callable(finish_deletions):
        await finish_deletions(roots)
    for root in sorted(roots):
        if await service.threads.find(root) is not None:
            await service.threads.remove(root, owner_id)


async def finish_file_operation(function, *args, **kwargs):
    """Do not release the admission lock while a cancelled worker still deletes."""
    return await _finish_operation(asyncio.to_thread(function, *args, **kwargs))


async def _finish_operation(operation):
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        # AnyIO cancellation is level-triggered; a plain second await would
        # cancel the to_thread Future while its filesystem worker keeps running.
        # Also resist repeated asyncio.Task.cancel() until the worker settles.
        with CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                cancellation.add_note(f"Cleanup operation also failed: {error!r}")
        raise cancellation


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
