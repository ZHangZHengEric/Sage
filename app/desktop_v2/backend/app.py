from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response as RawResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sagents.v2.contracts.session_commit import SessionMergeStrategy
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error

from app.desktop_v2.backend.service import (
    AgentSettingsPatch,
    ComponentSelectionRequest,
    DesktopRunRequest,
    DesktopV2Service,
    DesktopV2Settings,
    MCPConnectionRequest,
    ModelProviderCreate,
    ModelProviderPatch,
)
from app.desktop_v2.backend.anytool import DesktopV2AnyToolApp


def get_desktop_user_id(request: Request) -> str:
    return str(request.state.user_claims.get("userid") or "default_user")


class ProjectRequest(BaseModel):
    name: str = ""
    path: str


class SkillFolderImportRequest(BaseModel):
    path: str


class SteerRequest(BaseModel):
    turn_id: str
    text: str


class InteractionReplyRequest(BaseModel):
    interaction_id: str
    decision: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PublishSessionCommitRequest(BaseModel):
    merge_strategy: SessionMergeStrategy = SessionMergeStrategy.REQUIRE_UNCHANGED_BASE


class RejectSessionCommitRequest(BaseModel):
    reason: str = "rejected_by_user"


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


def create_app(*, service: DesktopV2Service | None = None) -> FastAPI:
    runtime_service = service or DesktopV2Service()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await runtime_service.initialize_agent_workspace()
            yield
        finally:
            close_store = getattr(runtime_service.session_store, "close", None)
            if close_store is not None:
                await close_store()

    app = FastAPI(
        title="Sage Desktop v2",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.v2_service = runtime_service
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
        user_id = str(request.headers.get("X-Sage-Internal-UserId") or "").strip()
        request.state.user_claims = {
            "userid": user_id or "default_user",
            "role": "admin",
        }
        return await call_next(request)

    @app.get("/health")
    async def health():
        return _success({"status": "ok", "protocol": "sage.runtime/v2"})

    @app.get("/active")
    async def active():
        return _success({"status": "ok", "protocol": "sage.runtime/v2"})

    @app.get("/api/v2/agents")
    async def list_agents(request: Request):
        return _success(
            await _safe(runtime_service.list_agents(get_desktop_user_id(request)))
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
    async def list_tools(request: Request):
        return _success(
            await _safe(runtime_service.list_tools(get_desktop_user_id(request)))
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
        content = await file.read()
        value = await _safe(
            runtime_service.upload(
                workspace_id, agent_id, file.filename or "attachment", content
            )
        )
        return _success(value)

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
    async def list_sessions():
        return _success(await _safe(runtime_service.list_sessions()))

    @app.get("/api/v2/sessions/{session_id}")
    async def get_session(session_id: str):
        return _success(await _safe(runtime_service.session_snapshot(session_id)))

    @app.delete("/api/v2/sessions/{session_id}")
    async def delete_session(session_id: str):
        await _safe(runtime_service.delete_session(session_id))
        return _success()

    @app.get("/api/v2/sessions/{session_id}/runs")
    async def list_session_runs(session_id: str):
        return _success(await _safe(runtime_service.session_runs(session_id)))

    @app.get("/api/v2/sessions/{session_id}/commit-proposals")
    async def list_session_commit_proposals(session_id: str):
        return _success(
            await _safe(runtime_service.session_commit_proposals(session_id))
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
        after_sequence: int = 0,
        limit: int | None = None,
    ):
        return _success(
            await _safe(
                runtime_service.session_events(
                    session_id,
                    after_sequence=after_sequence,
                    limit=limit,
                )
            )
        )

    @app.get("/api/v2/sessions/{session_id}/llm-requests")
    async def list_llm_requests(session_id: str, run_id: str | None = None):
        return _success(
            await _safe(runtime_service.list_llm_requests(session_id, run_id=run_id))
        )

    @app.get("/api/v2/sessions/{session_id}/runs/{run_id}/llm-requests/{request_id}")
    async def get_llm_request(session_id: str, run_id: str, request_id: str):
        return _success(
            await _safe(runtime_service.get_llm_request(session_id, run_id, request_id))
        )

    @app.get("/api/v2/runs/{run_id}")
    async def get_run(run_id: str):
        return _success(await _safe(runtime_service.snapshot(run_id)))

    @app.get("/api/v2/runs/{run_id}/events")
    async def subscribe_events(run_id: str, after_sequence: int = 0):
        return StreamingResponse(
            runtime_service.subscribe_events(run_id, after_sequence),
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
                run_id, body.turn_id, body.text, get_desktop_user_id(request)
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
