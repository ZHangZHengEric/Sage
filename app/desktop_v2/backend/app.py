from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable
from contextlib import asynccontextmanager
import json
import secrets
import time
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response as RawResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sagents.v2.contracts.session_commit import SessionMergeStrategy
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.common import new_id

from app.desktop_v2.backend.schemas import (
    AgentCreate,
    AgentSettingsPatch,
    ComponentSelectionRequest,
    DesktopRunRequest,
    DesktopV2Settings,
    MCPConnectionRequest,
    ModelProviderCreate,
    ModelProviderPatch,
    RunMessageContent,
)
from app.desktop_v2.backend.service import DesktopV2Service
from app.desktop_v2.backend.anytool import DesktopV2AnyToolApp
from app.desktop_v2.backend.runtime_protocol import (
    SIDECAR_PROTOCOL,
    SIDECAR_REVISION,
)
from app.desktop_v2.backend.sidecar_lifecycle import SidecarClientLeases
from app.desktop_v2.backend.terminal import TerminalSessionManager

_MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def get_desktop_user_id(request: Request) -> str:
    return str(request.state.user_claims.get("userid") or "default_user")


class ProjectRequest(BaseModel):
    name: str = ""
    path: str


class SkillFolderImportRequest(BaseModel):
    path: str


class SteerRequest(BaseModel):
    turn_id: str
    text: str = ""
    content: list[RunMessageContent] = Field(default_factory=list)


class InteractionReplyRequest(BaseModel):
    interaction_id: str
    decision: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PublishSessionCommitRequest(BaseModel):
    merge_strategy: SessionMergeStrategy = SessionMergeStrategy.REQUIRE_UNCHANGED_BASE


class RejectSessionCommitRequest(BaseModel):
    reason: str = "rejected_by_user"


class TerminalCreateRequest(BaseModel):
    agent_id: str
    workspace_id: str = ""
    columns: int = Field(default=100, ge=10, le=500)
    rows: int = Field(default=30, ge=2, le=500)


class TerminalInputRequest(BaseModel):
    data: str


class TerminalResizeRequest(BaseModel):
    columns: int = Field(ge=10, le=500)
    rows: int = Field(ge=2, le=500)


def _success(data: Any = None) -> dict[str, Any]:
    return {"code": 0, "message": "success", "data": data}


async def _safe(call):
    try:
        return await call
    except SageV2Error as exc:
        status = (
            404
            if exc.info.code.endswith("not_found")
            or exc.info.code.endswith("_not_found")
            else 409
            if exc.info.category == ErrorCategory.CONFLICT
            else 403
            if exc.info.category
            in {ErrorCategory.AUTHENTICATION, ErrorCategory.AUTHORIZATION}
            else 400
        )
        raise HTTPException(
            status_code=status,
            detail=exc.info.model_dump(mode="json"),
        ) from exc
    except (ValueError, RuntimeError, FileNotFoundError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_app(
    *,
    service: DesktopV2Service | None = None,
    terminal_manager: TerminalSessionManager | None = None,
    build_id: str = "manual",
    auth_token: str,
    shutdown_requested: Callable[[], None] | None = None,
    client_lease_ttl_seconds: float = 30.0,
) -> FastAPI:
    if not auth_token.strip():
        raise ValueError("Desktop sidecar auth token must not be empty")
    runtime_service = service or DesktopV2Service()
    terminals = terminal_manager or TerminalSessionManager()
    client_leases = SidecarClientLeases(ttl_seconds=client_lease_ttl_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        lease_watcher = (
            asyncio.create_task(
                client_leases.watch(shutdown_requested),
                name="desktop-sidecar-client-leases",
            )
            if shutdown_requested is not None
            else None
        )
        try:
            runtime_service.logger.info(
                "application.started",
                "Desktop API application started",
            )
            await runtime_service.initialize_agent_workspace()
            yield
        except Exception as exc:
            runtime_service.logger.exception(
                "application.lifecycle_failed",
                "Desktop API application lifecycle failed",
                exc,
            )
            raise
        finally:
            if lease_watcher is not None:
                lease_watcher.cancel()
                await asyncio.gather(lease_watcher, return_exceptions=True)
            await terminals.close()
            runtime_service.logger.info(
                "application.stopped",
                "Desktop API application stopped",
            )
            close_service = getattr(runtime_service, "close", None)
            if close_service is not None:
                await close_service()
            else:
                close_store = getattr(runtime_service.session_store, "close", None)
                if close_store is not None:
                    await close_store()

    app = FastAPI(
        title="Sage Desktop v2",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.v2_service = runtime_service
    app.state.terminal_manager = terminals
    app.state.client_leases = client_leases
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    desktop_catalog = getattr(runtime_service, "catalog", None)
    if desktop_catalog is not None:
        app.mount(
            "/api/mcp/anytool",
            DesktopV2AnyToolApp(desktop_catalog),
        )

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or new_id("request")
        request.state.request_id = request_id
        started = time.monotonic()
        supplied_token = request.headers.get("Authorization") or ""
        expected_token = f"Bearer {auth_token}"
        if not secrets.compare_digest(supplied_token, expected_token):
            runtime_service.logger.warning(
                "api.request.unauthenticated",
                "Desktop API request did not present the launch capability",
                request_id=request_id,
                attributes={"method": request.method, "path": request.url.path},
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid Desktop sidecar capability"},
                headers={
                    "WWW-Authenticate": "Bearer",
                    "X-Request-Id": request_id,
                },
            )
        request.state.user_claims = {
            "userid": "default_user",
            "role": "admin",
        }
        request_logger = runtime_service.logger.bind(request_id=request_id)
        quiet = request.url.path in {"/health", "/active"}
        (request_logger.debug if quiet else request_logger.info)(
            "api.request.started",
            "Desktop API request started",
            attributes={"method": request.method, "path": request.url.path},
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            request_logger.exception(
                "api.request.failed",
                "Desktop API request failed",
                exc,
                attributes={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            raise
        log = (
            request_logger.warning
            if response.status_code >= 400
            else request_logger.debug
            if quiet
            else request_logger.info
        )
        log(
            "api.request.completed",
            "Desktop API request completed",
            attributes={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(HTTPException)
    async def log_http_exception(request: Request, exc: HTTPException):
        request_id = getattr(request.state, "request_id", None)
        runtime_service.logger.warning(
            "api.request.rejected",
            "Desktop API request was rejected",
            request_id=request_id,
            attributes={
                "method": request.method,
                "path": request.url.path,
                "status_code": exc.status_code,
                "detail": exc.detail,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder({"detail": exc.detail}),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def log_validation_exception(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", None)
        errors = exc.errors()
        runtime_service.logger.warning(
            "api.request.validation_failed",
            "Desktop API request validation failed",
            request_id=request_id,
            attributes={
                "method": request.method,
                "path": request.url.path,
                "status_code": 422,
                "errors": errors,
            },
        )
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"detail": errors}),
        )

    @app.get("/health")
    async def health():
        return _success(
            {
                "status": "ok",
                "protocol": SIDECAR_PROTOCOL,
                "revision": SIDECAR_REVISION,
                "build_id": build_id,
            }
        )

    @app.get("/active")
    async def active():
        return _success(
            {
                "status": "ok",
                "protocol": SIDECAR_PROTOCOL,
                "revision": SIDECAR_REVISION,
                "build_id": build_id,
            }
        )

    @app.put("/api/v2/runtime/clients/{client_id}")
    async def attach_runtime_client(client_id: str):
        result = await _safe(client_leases.attach(client_id))
        return _success(
            {
                "active_clients": result.active_clients,
                "lease_ttl_seconds": client_leases.ttl_seconds,
            }
        )

    @app.delete("/api/v2/runtime/clients/{client_id}")
    async def detach_runtime_client(client_id: str):
        result = await _safe(client_leases.detach(client_id))
        if result.shutdown_requested and shutdown_requested is not None:
            asyncio.get_running_loop().call_soon(shutdown_requested)
        return _success(
            {
                "active_clients": result.active_clients,
                "shutdown_requested": result.shutdown_requested,
            }
        )

    @app.post("/api/v2/runtime/shutdown-if-idle")
    async def shutdown_runtime_if_idle():
        result = await _safe(client_leases.request_shutdown_if_idle())
        if result.shutdown_requested and shutdown_requested is not None:
            asyncio.get_running_loop().call_soon(shutdown_requested)
        return _success(
            {
                "active_clients": result.active_clients,
                "shutdown_requested": result.shutdown_requested,
            }
        )

    @app.get("/api/v2/agents")
    async def list_agents(request: Request):
        return _success(
            await _safe(runtime_service.list_agents(get_desktop_user_id(request)))
        )

    @app.post("/api/v2/agents")
    async def create_agent(value: AgentCreate, request: Request):
        return _success(
            await _safe(
                runtime_service.create_agent(value, get_desktop_user_id(request))
            )
        )

    @app.get("/api/v2/agents/{agent_id}/skills")
    async def list_skills(agent_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.list_skills(agent_id, get_desktop_user_id(request))
            )
        )

    @app.delete("/api/v2/agents/{agent_id}")
    async def delete_agent(agent_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.delete_agent(agent_id, get_desktop_user_id(request))
            )
        )

    @app.get("/api/v2/agents/{agent_id}/settings")
    async def get_agent_settings(agent_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.get_agent_settings(
                    agent_id, get_desktop_user_id(request)
                )
            )
        )

    @app.patch("/api/v2/agents/{agent_id}/settings")
    async def patch_agent_settings(
        agent_id: str, patch: AgentSettingsPatch, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.patch_agent_settings(
                    agent_id, patch, get_desktop_user_id(request)
                )
            )
        )

    @app.get("/api/v2/tools")
    async def list_tools(request: Request, lang: str | None = None):
        return _success(
            await _safe(
                runtime_service.list_tools(
                    get_desktop_user_id(request),
                    language=lang or request.headers.get("accept-language"),
                )
            )
        )

    @app.get("/api/v2/skills")
    async def list_skill_catalog(request: Request):
        return _success(
            await _safe(
                runtime_service.list_skill_catalog(get_desktop_user_id(request))
            )
        )

    @app.get("/api/v2/skills/{skill_name}/content")
    async def get_skill_content(skill_name: str, request: Request):
        return _success(
            await _safe(
                runtime_service.get_skill_content(
                    skill_name,
                    get_desktop_user_id(request),
                )
            )
        )

    @app.delete("/api/v2/skills/{skill_name}")
    async def delete_skill(skill_name: str, request: Request):
        return _success(
            await _safe(
                runtime_service.delete_skill(
                    skill_name,
                    get_desktop_user_id(request),
                )
            )
        )

    @app.post("/api/v2/skills/import-folder")
    async def import_skill_folder(
        value: SkillFolderImportRequest,
        request: Request,
    ):
        return _success(
            await _safe(
                runtime_service.import_skill_folder(
                    value.path,
                    get_desktop_user_id(request),
                )
            )
        )

    @app.get("/api/v2/model-providers")
    async def list_model_providers(request: Request):
        return _success(
            await _safe(
                runtime_service.list_model_providers(get_desktop_user_id(request))
            )
        )

    @app.post("/api/v2/model-providers")
    async def create_model_provider(value: ModelProviderCreate, request: Request):
        return _success(
            await _safe(
                runtime_service.create_model_provider(
                    value, get_desktop_user_id(request)
                )
            )
        )

    @app.post("/api/v2/model-providers/verify-capabilities")
    async def verify_new_model_provider_capabilities(
        value: ModelProviderCreate, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.verify_model_provider_capabilities(
                    value,
                    get_desktop_user_id(request),
                )
            )
        )

    @app.get("/api/v2/model-providers/{provider_id}/api-key")
    async def reveal_model_provider_api_key(provider_id: str, request: Request):
        data = await _safe(
            runtime_service.reveal_model_provider_api_key(
                provider_id, get_desktop_user_id(request)
            )
        )
        return JSONResponse(
            _success(data),
            headers={"Cache-Control": "no-store"},
        )

    @app.patch("/api/v2/model-providers/{provider_id}")
    async def patch_model_provider(
        provider_id: str, patch: ModelProviderPatch, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.patch_model_provider(
                    provider_id, patch, get_desktop_user_id(request)
                )
            )
        )

    @app.post("/api/v2/model-providers/{provider_id}/verify-capabilities")
    async def verify_existing_model_provider_capabilities(
        provider_id: str, value: ModelProviderPatch, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.verify_model_provider_capabilities(
                    value,
                    get_desktop_user_id(request),
                    provider_id=provider_id,
                )
            )
        )

    @app.delete("/api/v2/model-providers/{provider_id}")
    async def delete_model_provider(provider_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.delete_model_provider(
                    provider_id, get_desktop_user_id(request)
                )
            )
        )

    @app.get("/api/v2/mcp-connections")
    async def list_mcp_connections(request: Request):
        return _success(
            await _safe(
                runtime_service.list_mcp_connections(get_desktop_user_id(request))
            )
        )

    @app.post("/api/v2/mcp-connections")
    async def add_mcp_connection(value: MCPConnectionRequest, request: Request):
        return _success(
            await _safe(
                runtime_service.add_mcp_connection(value, get_desktop_user_id(request))
            )
        )

    @app.put("/api/v2/mcp-connections/{server_name}/enabled")
    async def set_mcp_connection_enabled(
        server_name: str, enabled: bool, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.set_mcp_connection_enabled(
                    server_name, enabled, get_desktop_user_id(request)
                )
            )
        )

    @app.get("/api/v2/components")
    async def component_inventory(request: Request):
        return _success(
            await _safe(
                runtime_service.component_inventory(get_desktop_user_id(request))
            )
        )

    @app.put("/api/v2/components/{component_id}/selection")
    async def select_component(
        component_id: str, value: ComponentSelectionRequest, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.select_component(
                    component_id, value, get_desktop_user_id(request)
                )
            )
        )

    @app.get("/api/v2/settings")
    async def get_settings():
        value = await runtime_service.get_settings()
        return _success(value.model_dump(mode="json"))

    @app.put("/api/v2/settings")
    async def put_settings(settings: DesktopV2Settings):
        value = await _safe(runtime_service.save_settings(settings))
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/projects")
    async def add_project(body: ProjectRequest):
        value = await _safe(runtime_service.add_project(body.name, body.path))
        return _success(value.model_dump(mode="json"))

    @app.delete("/api/v2/projects/{project_id}")
    async def remove_project(project_id: str):
        await _safe(runtime_service.remove_project(project_id))
        return _success({"project_id": project_id})

    @app.get("/api/v2/workspaces/tree")
    async def workspace_tree(agent_id: str, workspace_id: str | None = None):
        files = await _safe(runtime_service.workspace_tree(workspace_id, agent_id))
        return _success({"files": files})

    @app.get("/api/v2/workspaces/file")
    async def workspace_file(agent_id: str, path: str, workspace_id: str | None = None):
        content, media_type = await _safe(
            runtime_service.read_file(workspace_id, agent_id, path)
        )
        return RawResponse(content=content, media_type=media_type)

    @app.post("/api/v2/workspaces/upload")
    async def workspace_upload(
        file: UploadFile = File(...),
        agent_id: str = Form(...),
        workspace_id: str | None = Form(None),
    ):
        content = await file.read(_MAX_UPLOAD_BYTES + 1)
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload exceeds 64 MiB limit")
        value = await _safe(
            runtime_service.upload(
                workspace_id, agent_id, file.filename or "attachment", content
            )
        )
        return _success(value)

    def terminal_session(session_id: str, request: Request):
        try:
            return terminals.get(session_id, get_desktop_user_id(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v2/terminals")
    async def create_terminal(body: TerminalCreateRequest, request: Request):
        workspace = await _safe(
            runtime_service.workspace_root(body.workspace_id, body.agent_id)
        )
        session = await _safe(
            terminals.create(
                owner_id=get_desktop_user_id(request),
                cwd=workspace,
                columns=body.columns,
                rows=body.rows,
            )
        )
        return _success(session.snapshot())

    @app.get("/api/v2/terminals/{session_id}/events")
    async def terminal_events(
        session_id: str,
        request: Request,
        after_sequence: int = 0,
    ):
        session = terminal_session(session_id, request)

        async def response_stream():
            async for event in session.events(max(0, after_sequence)):
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(
            response_stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v2/terminals/{session_id}/input")
    async def terminal_input(
        session_id: str,
        body: TerminalInputRequest,
        request: Request,
    ):
        session = terminal_session(session_id, request)
        try:
            data = base64.b64decode(body.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="terminal input must be valid base64",
            ) from exc
        await _safe(session.write(data))
        return _success({"accepted": len(data)})

    @app.post("/api/v2/terminals/{session_id}/resize")
    async def terminal_resize(
        session_id: str,
        body: TerminalResizeRequest,
        request: Request,
    ):
        session = terminal_session(session_id, request)
        await _safe(session.resize(body.columns, body.rows))
        return _success(
            {
                "columns": session.columns,
                "rows": session.rows,
            }
        )

    @app.delete("/api/v2/terminals/{session_id}")
    async def close_terminal(session_id: str, request: Request):
        terminal_session(session_id, request)
        await _safe(terminals.close_session(session_id, get_desktop_user_id(request)))
        return _success({"session_id": session_id})

    @app.post("/api/v2/runs/stream")
    async def run_stream(body: DesktopRunRequest, request: Request):
        stream = runtime_service.run_events(body, get_desktop_user_id(request))
        try:
            first = await anext(stream)
        except (ValueError, RuntimeError, FileNotFoundError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async def response_stream():
            yield first
            async for item in stream:
                yield item

        return StreamingResponse(
            response_stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v2/sessions")
    async def list_sessions(request: Request):
        return _success(
            await _safe(runtime_service.list_sessions(get_desktop_user_id(request)))
        )

    @app.get("/api/v2/usage/overview")
    async def usage_overview(
        request: Request,
        days: int = 30,
        timezone_offset_minutes: int = 0,
    ):
        return _success(
            await _safe(
                runtime_service.usage_overview(
                    get_desktop_user_id(request),
                    days=days,
                    timezone_offset_minutes=timezone_offset_minutes,
                )
            )
        )

    @app.get("/api/v2/sessions/{session_id}")
    async def get_session(session_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.session_snapshot(
                    session_id, get_desktop_user_id(request)
                )
            )
        )

    @app.delete("/api/v2/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request):
        await _safe(
            runtime_service.delete_session(session_id, get_desktop_user_id(request))
        )
        return _success()

    @app.get("/api/v2/sessions/{session_id}/runs")
    async def list_session_runs(session_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.session_runs(session_id, get_desktop_user_id(request))
            )
        )

    @app.get("/api/v2/sessions/{session_id}/tree")
    async def get_session_tree(session_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.session_tree(session_id, get_desktop_user_id(request))
            )
        )

    @app.get("/api/v2/sessions/{session_id}/tree/events")
    async def subscribe_session_tree(session_id: str, request: Request):
        return StreamingResponse(
            runtime_service.subscribe_session_tree(
                session_id, get_desktop_user_id(request)
            ),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v2/sessions/{session_id}/commit-proposals")
    async def list_session_commit_proposals(session_id: str, request: Request):
        return _success(
            await _safe(
                runtime_service.session_commit_proposals(
                    session_id, get_desktop_user_id(request)
                )
            )
        )

    @app.post("/api/v2/runs/{run_id}/commit-proposals")
    async def propose_session_commit(run_id: str, request: Request):
        value = await _safe(
            runtime_service.propose_session_commit(run_id, get_desktop_user_id(request))
        )
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/session-commit-proposals/{proposal_id}/publish")
    async def publish_session_commit(
        proposal_id: str,
        body: PublishSessionCommitRequest,
        request: Request,
    ):
        value = await _safe(
            runtime_service.publish_session_commit(
                proposal_id,
                body.merge_strategy,
                get_desktop_user_id(request),
            )
        )
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/session-commit-proposals/{proposal_id}/reject")
    async def reject_session_commit(
        proposal_id: str,
        body: RejectSessionCommitRequest,
        request: Request,
    ):
        value = await _safe(
            runtime_service.reject_session_commit(
                proposal_id,
                body.reason,
                get_desktop_user_id(request),
            )
        )
        return _success(value.model_dump(mode="json"))

    @app.get("/api/v2/sessions/{session_id}/events")
    async def list_session_events(
        session_id: str,
        request: Request,
        after_sequence: int = 0,
        limit: int | None = None,
    ):
        return _success(
            await _safe(
                runtime_service.session_events(
                    session_id,
                    get_desktop_user_id(request),
                    after_sequence=after_sequence,
                    limit=limit,
                )
            )
        )

    @app.get("/api/v2/sessions/{session_id}/llm-requests")
    async def list_llm_requests(
        session_id: str, request: Request, run_id: str | None = None
    ):
        return _success(
            await _safe(
                runtime_service.list_llm_requests(
                    session_id,
                    get_desktop_user_id(request),
                    run_id=run_id,
                )
            )
        )

    @app.get("/api/v2/sessions/{session_id}/runs/{run_id}/llm-requests/{request_id}")
    async def get_llm_request(
        session_id: str, run_id: str, request_id: str, request: Request
    ):
        return _success(
            await _safe(
                runtime_service.get_llm_request(
                    session_id,
                    run_id,
                    request_id,
                    get_desktop_user_id(request),
                )
            )
        )

    @app.get("/api/v2/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        return _success(
            await _safe(runtime_service.snapshot(run_id, get_desktop_user_id(request)))
        )

    @app.get("/api/v2/runs/{run_id}/events")
    async def subscribe_events(run_id: str, request: Request, after_sequence: int = 0):
        return StreamingResponse(
            runtime_service.subscribe_events(
                run_id, after_sequence, get_desktop_user_id(request)
            ),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v2/runs/{run_id}/pause")
    async def pause_run(run_id: str, request: Request):
        value = await _safe(runtime_service.pause(run_id, get_desktop_user_id(request)))
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/runs/{run_id}/resume")
    async def resume_run(run_id: str, request: Request):
        value = await _safe(
            runtime_service.resume(run_id, get_desktop_user_id(request))
        )
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request):
        value = await _safe(
            runtime_service.cancel(run_id, get_desktop_user_id(request))
        )
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/runs/{run_id}/steer")
    async def steer_run(run_id: str, body: SteerRequest, request: Request):
        value = await _safe(
            runtime_service.steer(
                run_id,
                body.turn_id,
                body.text,
                get_desktop_user_id(request),
                content=body.content,
            )
        )
        return _success(value.model_dump(mode="json"))

    @app.post("/api/v2/runs/{run_id}/interactions/reply")
    async def reply_interaction(
        run_id: str, body: InteractionReplyRequest, request: Request
    ):
        value = await _safe(
            runtime_service.reply_interaction(
                run_id,
                body.interaction_id,
                body.decision,
                body.payload,
                get_desktop_user_id(request),
            )
        )
        return _success(value.model_dump(mode="json"))

    return app
