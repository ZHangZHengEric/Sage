"""Authenticated workspace browsing and administrator Session folder downloads."""
from __future__ import annotations

import asyncio
from functools import partial
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.v2.server.routers.deps import AdminUser, HostDep, ReadUser
from app.v2.server.routers.render import success
from app.v2.server.storage.downloads import list_directory, prepare_download
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore

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


@router.get("/api/workspace/files")
async def workspace_files(user: ReadUser, host: HostDep, path: str = Query(default="", max_length=4096)):
    root = host.paths.tenants_root / user.user_id / "workspace"
    if not root.exists() and not path:
        return success([])
    return success(await file_operation(list_directory, root, path))


@router.get("/api/workspace/download")
async def workspace_download(user: ReadUser, host: HostDep, path: str = Query(default="", max_length=4096)):
    root = host.paths.tenants_root / user.user_id / "workspace"
    return download_response(await file_operation(prepare_download, root, path))


@router.get("/api/threads/{thread_id}/download")
async def session_download(thread_id: str, user: AdminUser, host: HostDep):
    record = await host.threads.find(thread_id)
    if record is None:
        raise HTTPException(404, "thread not found")
    service = host.conversations
    # Validate the persisted Session owner before resolving its storage directory.
    await service.session_access.get_session(thread_id, service.context_for(record.user_id))
    store = service.application.entrypoint().runtime.session_store
    if not isinstance(store, FilesystemSessionStore):
        raise HTTPException(409, "this Session store has no filesystem directory")
    root = await store.session_directory(thread_id)
    name = root.name
    return download_response(await file_operation(prepare_download, root, "", archive_name=name))
