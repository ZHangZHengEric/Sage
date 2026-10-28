"""HTTP endpoints for conversation runs, threads, and pending approvals."""

import errno
import asyncio
import sqlite3
from typing import Annotated, Literal

import httpx
from ag_ui.core import RunAgentInput
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.v2.server.conversations import external_runs as access
from app.v2.server.conversations.cleanup import (
    delete_external_session, finish_file_operation, require_idle, reject_local_workspace_drive,
)
from app.v2.server.routers.deps import (
    AdminUser,
    ChatCallerDep,
    ConversationDep,
    CurrentUser,
    HostDep,
    ReadUser,
    PackageDep,
)
from app.v2.server.routers.files import download_response, file_operation
from app.v2.server.routers.render import error_response, success
from app.v2.server.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse, ErrorBody
from app.v2.server.routers.schemas.conversations import (
    AgentRunBody,
    ThreadEventPage,
    ThreadPublic, ThreadListPage,
    ThreadResumeBody,
    ThreadCancelBody,
    ThreadSteerBody,
)
from app.v2.server.storage.downloads import prepare_download, prepare_session_export
from app.v2.server.storage.external_workspaces import (
    delete_workspace_path,
    import_workspace_files,
    workspace_parts,
)
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.observability.contracts import DiagnosticEvidenceSource

agent_router = APIRouter(prefix="/api", tags=["agent"], responses=AUTH_ERRORS)
thread_router = APIRouter(
    prefix="/api/threads",
    tags=["threads"],
    responses={**AUTH_ERRORS, 404: {"description": "thread not found"}},
)
approval_router = APIRouter(
    prefix="/api/approvals", tags=["approvals"], responses=AUTH_ERRORS
)
download_router = APIRouter(tags=["files"])
external_router = APIRouter(
    prefix="/api/agents/{agent_id}", tags=["agent-runs"],
    responses=VALIDATION_ERRORS,
)


@agent_router.post(
    "/agent",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "AG-UI 0.1.19 SSE event stream",
        },
        404: {"model": ErrorBody, "description": "thread not found"},
        422: {"model": ErrorBody, "description": "invalid run input"},
    },
)
async def run_agent(
    body: AgentRunBody,
    request: Request,
    caller: ChatCallerDep,
    service: ConversationDep,
):
    last_event_id = (request.headers.get("last-event-id") or "").strip() or None
    stream = await service.start(
        body.to_agui(), user_id=caller.user_id,
        agent_id=caller.agent_id, last_event_id=last_event_id, api_key=caller.api_key,
        notification_connection_id=body.notification_connection_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Sage-AG-UI-Replay": "session-store",
        },
    )




class PackageRunBody(AgentRunBody):
    agent_package: AgentPackageBundle

    def to_agui(self):
        payload = self.model_dump(exclude={"session_id", "agent_package", "notification_connection_id"})
        payload["forwardedProps"] = {**self.forwardedProps,
            "agentId": self.agent_package.manifest.entrypoint.agent}
        return RunAgentInput.model_validate(payload)


@agent_router.post("/agent-package", response_class=StreamingResponse)
async def run_agent_package(body: PackageRunBody, request: Request,
                            user: CurrentUser, host: HostDep, service: ConversationDep, management: PackageDep):
    context = host.contexts.for_user(user.user_id)
    from app.v2.server.routers.packages import result
    await result(management.authorize_package("run", body.agent_package, context))
    stream = await service.start(body.to_agui(), user_id=user.user_id,
        package=body.agent_package,
        notification_connection_id=body.notification_connection_id,
        last_event_id=(request.headers.get("last-event-id") or "").strip() or None)
    return StreamingResponse(stream, media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        "X-Sage-AG-UI-Replay": "session-store",
    })


@thread_router.get("", response_model=ApiResponse[ThreadListPage])
async def list_threads(user: ReadUser, service: ConversationDep,
                       limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=2048),
                       search: str = Query("", max_length=512), agent_id: str = Query("", max_length=191)):
    page = await service.list_threads(user.user_id, limit=limit, cursor=cursor, search=search, agent_id=agent_id)
    return success(page.model_dump(mode="json"))


@thread_router.get("/{thread_id}", response_model=ApiResponse[ThreadPublic])
async def get_thread(thread_id: str, user: ReadUser, host: HostDep):
    from app.v2.server.conversations.records import require_owned_thread
    record = require_owned_thread(await host.threads.find(thread_id), user.user_id)
    return success(record.model_dump(mode="json"))


@thread_router.get("/{thread_id}/package")
async def get_thread_package(thread_id: str, user: ReadUser, service: ConversationDep):
    return success(await service.package_for_thread(thread_id, user.user_id))


@thread_router.get("/{thread_id}/events", response_model=ApiResponse[ThreadEventPage])
async def get_thread_events(
    thread_id: str,
    user: ReadUser,
    service: ConversationDep,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int | None = Query(
        default=None,
        ge=0,
        description="Session sequence already delivered. Omit for the newest page.",
    ),
):
    return success(
        await service.events(thread_id, user.user_id, limit=limit, offset=offset)
    )


@thread_router.post(
    "/{thread_id}/resume",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "AG-UI 0.1.19 SSE event stream",
        },
        409: {"description": "thread is not waiting for input"},
        422: {"description": "decision not offered by the pending question"},
    },
)
async def resume_thread(
    thread_id: str,
    body: ThreadResumeBody,
    request: Request,
    user: CurrentUser,
    service: ConversationDep,
):
    """Answer a waiting thread and stream the work the answer releases."""
    last_event_id = (request.headers.get("last-event-id") or "").strip() or None
    stream = await service.resume(
        thread_id,
        run_id=body.runId,
        user_id=user.user_id,
        decision=body.decision,
        payload=body.payload,
        last_event_id=last_event_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Sage-AG-UI-Replay": "session-store",
        },
    )


@thread_router.post("/{thread_id}/cancel")
async def cancel_thread_run(
    thread_id: str,
    body: ThreadCancelBody,
    user: CurrentUser,
    service: ConversationDep,
):
    return success(await service.cancel(thread_id, run_id=body.runId, user_id=user.user_id))


@thread_router.post("/{thread_id}/steer")
async def steer_thread_run(
    thread_id: str,
    body: ThreadSteerBody,
    user: CurrentUser,
    service: ConversationDep,
):
    return success(await service.steer(
        thread_id, run_id=body.runId, user_id=user.user_id,
        message_id=body.messageId, text=body.text,
    ))


@thread_router.delete("/{thread_id}", response_model=ApiResponse[None])
async def delete_thread(thread_id: str, user: CurrentUser, service: ConversationDep):
    await service.delete(thread_id, user.user_id, admin=user.role == "admin")
    return success()


@thread_router.get("/{thread_id}/result")
async def get_thread_result(
    thread_id: str,
    caller: ChatCallerDep,
    service: ConversationDep,
    run_id: str | None = Query(default=None, alias="runId", min_length=1, max_length=128),
):
    result = await service.result(
        user_id=caller.user_id, agent_id=caller.agent_id,
        session_id=thread_id, run_id=run_id,
    )
    return success(result)


@download_router.get("/api/threads/{thread_id}/download")
async def session_download(thread_id: str, user: AdminUser, host: HostDep, service: ConversationDep):
    record = await host.threads.find(thread_id)
    if record is None:
        raise HTTPException(404, "thread not found")
    # Validate the persisted Session owner before resolving its storage directory.
    await service.session_access.get_session(
        thread_id, service.context_for(record.user_id)
    )
    binding = await host.threads.binding(thread_id)
    if binding is not None and (
        binding.owner_id != record.user_id or binding.agent_id != record.agent_id
    ):
        raise HTTPException(404, "thread not found")
    context = service.context_for(record.user_id)
    runs = await service.session_access.list_session_runs(thread_id, context)
    for run in runs:
        command = await service.session_access.get_start_command(run.run_id, context)
        tenant = command.config.metadata.get("server_v2.workspace_user_id")
        if run.session_id != thread_id or command.agent_id != record.agent_id or (
            binding is not None and tenant is not None and tenant != binding.tenant_id
        ):
            raise HTTPException(404, "thread not found")
    run_ids = {run.run_id for run in runs}
    source: DiagnosticEvidenceSource | None = host.observability
    if source is None or host.diagnostics is None:
        raise HTTPException(409, "当前观测插件不支持诊断查询")
    try:
        async with asyncio.timeout(30):
            evidence = await source.export_evidence(thread_id, run_ids)
    except NotImplementedError as exc:
        raise HTTPException(409, "当前观测插件不支持诊断查询") from exc
    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, TimeoutError) as exc:
        raise HTTPException(503, "诊断数据暂不可用") from exc
    return download_response(
        await file_operation(prepare_session_export, thread_id, run_ids, evidence)
    )


class ApprovalExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interaction_id: str
    revision: int = Field(ge=0)
    suspension_revision: int = Field(ge=0)
    interaction_revision: int = Field(ge=0)


class ApprovalDecisionBody(BaseModel):
    decision: Literal["approve_once", "deny", "cancel"]
    expected: ApprovalExpected
    payload: dict = Field(default_factory=dict)


class PendingApproval(BaseModel):
    run_id: str
    thread_id: str
    title: str
    interaction: dict
    expires_at: str
    expected: ApprovalExpected


class ApprovalPage(BaseModel):
    items: list[PendingApproval]
    next_cursor: str | None


class ApprovalAccepted(BaseModel):
    session_id: str
    run_id: str
    accepted: bool


@approval_router.get("", response_model=ApiResponse[ApprovalPage])
async def list_approvals(
    user: ReadUser,
    service: ConversationDep,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=2048),
):
    return success(await service.pending_approvals(user.user_id, limit=limit, cursor=cursor))


@approval_router.post("/{run_id}/decisions", response_model=ApiResponse[ApprovalAccepted])
async def decide_approval(
    run_id: str, body: ApprovalDecisionBody,
    user: CurrentUser, service: ConversationDep,
):
    return success(await service.decide_approval(
        run_id, user_id=user.user_id, decision=body.decision,
        payload=body.payload, expected=body.expected.model_dump(),
    ))


def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="server.external_runs." + code, category=category, message=message,
    ))


class Caller:
    def __init__(self, tenant_id: str, agent_id: str, api_key):
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.api_key = api_key


async def internal_caller(
    request: Request,
    host: HostDep,
    agent_id: str,
    tenant_id: Annotated[str, Header(alias="SAGE-TENANT-ID", min_length=1, max_length=128)],
) -> Caller:
    if not tenant_id.strip():
        raise _error("invalid_tenant", ErrorCategory.VALIDATION,
                     "tenant ID is required")
    from app.v2.server.identity.external import authorize_external_agent
    key = await authorize_external_agent(request, host, agent_id)
    return Caller(tenant_id, agent_id, key)


CallerDep = Annotated[Caller, Depends(internal_caller)]


class WorkspaceImport(BaseModel):
    directory: str = Field(min_length=1, max_length=4096)
    files: dict[str, str] = Field(default_factory=dict)


class ExternalRunBody(AgentRunBody):
    runtimeContext: dict = Field(default_factory=dict)

    def to_agui(self) -> RunAgentInput:
        return RunAgentInput.model_validate(self.model_dump(exclude={"runtimeContext", "session_id", "notification_connection_id"}))


class InteractionReply(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=256)
    decision: str = Field(min_length=1, max_length=128)
    payload: dict = Field(default_factory=dict)
    expected: dict = Field(default_factory=dict)


@external_router.put("/workspace/files")
async def put_workspace_files(body: WorkspaceImport, caller: CallerDep, host: HostDep, service: ConversationDep):
    try:
        async with service.runs.workspace_guard(caller.tenant_id, caller.agent_id):
            count = await finish_file_operation(import_workspace_files, host.paths,
                                                caller.tenant_id, caller.agent_id,
                                                body.directory, body.files)
    except FileExistsError as exc:
        raise _error("workspace_conflict", ErrorCategory.CONFLICT,
                     "workspace file conflicts with existing data") from exc
    except (ValueError, OSError) as exc:
        raise _error("invalid_workspace", ErrorCategory.VALIDATION,
                     "invalid workspace files") from exc
    return success({"directory": body.directory, "file_count": count})


@external_router.delete("/workspace/files")
async def delete_workspace_files(caller: CallerDep, host: HostDep,
                                 service: ConversationDep,
                                 path: str = Query(min_length=1, max_length=4096),
                                 recursive: bool = False):
    try:
        workspace_parts(path)
    except ValueError:
        return error_response(status_code=422, message="invalid workspace path",
                              detail="invalid_workspace_path")
    reject_local_workspace_drive(service, caller.tenant_id, caller.agent_id)
    async with service.runs.workspace_guard(caller.tenant_id, caller.agent_id):
        await require_idle(service, caller.tenant_id, caller.agent_id, owner_id=caller.api_key.owner_user_id)
        try:
            deleted = await finish_file_operation(
                delete_workspace_path, host.paths, caller.tenant_id,
                caller.agent_id, path, recursive=recursive)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
                status, code = 403, "workspace_permission_denied"
            elif exc.errno in {errno.EBUSY, errno.ETXTBSY}:
                status, code = 409, "workspace_busy"
            elif exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                status, code = 422, "invalid_workspace_path"
            elif exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                status, code = 409, "workspace_not_empty"
            else:
                status, code = 500, "workspace_storage_failure"
            return error_response(status_code=status, message=code, detail=code)
        return success({"path": path, "deleted": deleted})


@external_router.delete("/sessions/{session_id}")
async def delete_agent_session(session_id: str, caller: CallerDep,
                                service: ConversationDep):
    internal_id = await delete_external_session(
        service, caller.tenant_id, caller.agent_id, session_id)
    return success({"session_id": internal_id})


@external_router.post("/runs", response_class=StreamingResponse)
async def start_run(body: ExternalRunBody, request: Request, caller: CallerDep,
                    host: HostDep, service: ConversationDep,
                    workspace_path: str | None = Query(default=None, max_length=4096)):
    if workspace_path is not None:
        try:
            workspace_path = "/".join(workspace_parts(workspace_path))
        except (ValueError, OSError) as exc:
            raise _error("invalid_workspace", ErrorCategory.VALIDATION,
                         "invalid workspace directory") from exc
    last_event_id = (request.headers.get("last-event-id") or "").strip() or None
    stream = await service.start(body.to_agui(), user_id=caller.tenant_id,
                                 agent_id=caller.agent_id, api_key=caller.api_key,
                                 workspace_directory=workspace_path,
                                 runtime_context=body.runtimeContext,
                                 notification_connection_id=body.notification_connection_id,
                                 last_event_id=last_event_id)
    return StreamingResponse(stream, media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        "X-Sage-AG-UI-Replay": "session-store",
    })


@external_router.get("/runs/{thread_id}/{run_id}")
async def get_run(thread_id: str, run_id: str, caller: CallerDep,
                  service: ConversationDep):
    return success(await access.run_details(service, tenant_id=caller.tenant_id,
                                            agent_id=caller.agent_id,
                                            thread_id=thread_id, run_id=run_id))


@external_router.post("/runs/{thread_id}/{run_id}/reply")
async def reply_run(thread_id: str, run_id: str, body: InteractionReply,
                    caller: CallerDep, service: ConversationDep):
    session_id = await access.reply_run(service, tenant_id=caller.tenant_id,
                           agent_id=caller.agent_id, thread_id=thread_id,
                           run_id=run_id, interaction_id=body.interaction_id,
                           decision=body.decision, payload=body.payload,
                           expected=body.expected)
    return success({"session_id": session_id, "accepted": True})


@external_router.post("/runs/{thread_id}/{run_id}/cancel")
async def cancel_run(thread_id: str, run_id: str, caller: CallerDep,
                     service: ConversationDep):
    result = await access.cancel_run(service, tenant_id=caller.tenant_id,
                                        agent_id=caller.agent_id, thread_id=thread_id,
                                        run_id=run_id)
    return success(result)


@external_router.get("/runs/{thread_id}/{run_id}/files")
async def download_run_files(thread_id: str, run_id: str, caller: CallerDep,
                             service: ConversationDep, host: HostDep):
    directory = await access.current_run_workspace(
        service, tenant_id=caller.tenant_id, agent_id=caller.agent_id,
        thread_id=thread_id, run_id=run_id,
    )
    root = host.paths.workspace_path(caller.tenant_id, caller.agent_id)
    prepared = await file_operation(prepare_download, root, directory,
                                    max_bytes=32 << 20, max_entries=512)
    try:
        # A newer run may have started while the archive was being built.
        await access.current_run_workspace(
            service, tenant_id=caller.tenant_id, agent_id=caller.agent_id,
            thread_id=thread_id, run_id=run_id,
        )
    except BaseException:
        prepared[0].close()
        raise
    return download_response(prepared)

router = APIRouter()
router.include_router(agent_router)
router.include_router(thread_router)
router.include_router(approval_router)
router.include_router(download_router)
router.include_router(external_router)
