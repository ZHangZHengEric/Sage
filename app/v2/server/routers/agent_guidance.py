"""Agent-scoped prompt and Skill ZIP sync endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.v2.server.identity.keys import SCOPE_AGENT_GUIDANCE_WRITE, require_scope
from app.v2.server.routers.deps import HostDep
from app.v2.server.routers.render import success
from app.v2.server.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.v2.server.skills.agent_guidance import sync_agent_guidance
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

router = APIRouter(tags=["agents"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})
_bearer = HTTPBearer(auto_error=False)


@router.put("/api/agents/{agent_id}/guidance", response_model=ApiResponse[dict])
async def put_agent_guidance(
    agent_id: str,
    host: HostDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    prompt: Annotated[str, Form(min_length=1)],
    files: Annotated[list[UploadFile], File()],
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.unauthenticated",
            category=ErrorCategory.AUTHENTICATION, message="authentication required"))
    key = require_scope(await host.credentials.authenticate(credentials.credentials), SCOPE_AGENT_GUIDANCE_WRITE)
    if key.agent_id != agent_id:
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.forbidden",
            category=ErrorCategory.AUTHORIZATION, message="Agent is outside credential scope"))
    if len(files) > 32:
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.validation",
            category=ErrorCategory.VALIDATION, message="too many Skill ZIP files"))
    uploads = [(item.filename or "unknown.zip", await item.read((32 << 20) + 1)) for item in files]
    try:
        result = await sync_agent_guidance(host, owner_id=key.owner_user_id,
                                          agent_id=agent_id, prompt=prompt, files=uploads)
    except ValueError as exc:
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.validation",
            category=ErrorCategory.VALIDATION, message=str(exc))) from exc
    return success(result)
