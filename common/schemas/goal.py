from enum import Enum
from typing import Optional

from pydantic import BaseModel


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class SessionGoal(BaseModel):
    objective: str
    status: GoalStatus = GoalStatus.ACTIVE
    created_at: float
    updated_at: float
    completed_at: Optional[float] = None
    paused_reason: Optional[str] = None


class GoalTransition(BaseModel):
    type: str
    objective: Optional[str] = None
    status: Optional[str] = None
    previous_objective: Optional[str] = None
    previous_status: Optional[str] = None


class GoalMutation(BaseModel):
    objective: Optional[str] = None
    status: Optional[GoalStatus] = None
    clear: bool = False


class GoalSetRequest(BaseModel):
    objective: str
    status: GoalStatus = GoalStatus.ACTIVE
