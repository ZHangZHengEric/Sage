"""Authenticated workspace browsing and downloads."""
from __future__ import annotations

import asyncio
from functools import partial
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.v2.server.routers.deps import HostDep, ReadUser, CurrentUser
from app.v2.server.routers.render import success
from app.v2.server.storage.downloads import list_directory, prepare_download

router = APIRouter(tags=["files"])


async def file_operation(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(partial(function, *args, **kwargs))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (OSError, RecursionError) as exc:
        raise HTTPException(404, "file or directory not found") from exc
    except OverflowError as exc:
        raise HTTPException(413, str(exc)) from exc


def download_response(prepared):
    stream, filename = prepared
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)

    def chunks():
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        chunks(), media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
                 "Content-Length": str(size), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(stream.close),
    )


async def workspace_root(host, caller, read_user, thread_id, agent_id):
    owner_id = read_user.user_id
    if thread_id:
        record = await host.threads.find(thread_id)
        if record is None or (caller.role != "admin" and record.user_id != caller.user_id):
            raise HTTPException(404, "thread not found")
        await host.conversations.session_access.get_session(
            thread_id, host.conversations.context_for(record.user_id)
        )
        owner_id = record.user_id
        context = host.conversations.context_for(owner_id)
        access = host.conversations.session_access
        runs = await access.list_session_runs(thread_id, context)
        if runs:
            latest = max(runs, key=lambda run: (run.accepted_session_revision, run.created_at, run.run_id))
            command = await access.get_start_command(latest.run_id, context)
            from app.v2.server.storage.workspaces import workspace_user
            owner_id = workspace_user(command, owner_id)
            agent_id = command.agent_id
        else:
            agent_id = record.agent_id
    elif agent_id:
        catalog = await host.catalog.get(owner_id)
        if not any(agent.id == agent_id for agent in catalog.agents):
            raise HTTPException(404, "agent not found")
    if not agent_id:
        raise HTTPException(400, "agent_id or thread_id is required")
    return host.paths.workspace_path(owner_id, agent_id)


@router.get("/api/workspace/files")
async def workspace_files(user: ReadUser, caller: CurrentUser, host: HostDep,
                          path: str = Query(default="", max_length=4096),
                          thread_id: str | None = Query(default=None, min_length=1, max_length=256),
                          agent_id: str | None = Query(default=None, min_length=1, max_length=256)):
    root = await workspace_root(host, caller, user, thread_id, agent_id)
    if not root.exists() and not path:
        return success([])
    return success(await file_operation(list_directory, root, path))


@router.get("/api/workspace/download")
async def workspace_download(user: ReadUser, caller: CurrentUser, host: HostDep,
                             path: str = Query(default="", max_length=4096),
                             thread_id: str | None = Query(default=None, min_length=1, max_length=256),
                          agent_id: str | None = Query(default=None, min_length=1, max_length=256)):
    root = await workspace_root(host, caller, user, thread_id, agent_id)
    return download_response(await file_operation(prepare_download, root, path))
