from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.v2.server.routers.deps import ConversationDep, CurrentUser
from app.v2.server.routers.render import success
from app.v2.server.routers.schemas.common import AUTH_ERRORS, ApiResponse

router = APIRouter(prefix="/api/approvals", tags=["approvals"], responses=AUTH_ERRORS)


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
    next_offset: int | None


class ApprovalAccepted(BaseModel):
    run_id: str
    accepted: bool


@router.get("", response_model=ApiResponse[ApprovalPage])
async def list_approvals(user: CurrentUser, service: ConversationDep,
                         limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return success(await service.pending_approvals(user.user_id, limit=limit, offset=offset))


@router.post("/{run_id}/decisions", response_model=ApiResponse[ApprovalAccepted])
async def decide_approval(run_id: str, body: ApprovalDecisionBody,
                          user: CurrentUser, service: ConversationDep):
    return success(await service.decide_approval(run_id, user_id=user.user_id,
        decision=body.decision, payload=body.payload, expected=body.expected.model_dump()))
