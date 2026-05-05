from pydantic import BaseModel

from common.schemas.goal import GoalTransition, SessionGoal


class ConversationInfo(BaseModel):
    session_id: str
    agent_id: str
    agent_name: str
    title: str
    message_count: int
    user_count: int
    agent_count: int
    created_at: str
    updated_at: str
    user_id: str | None = None
    trace_id: str | None = None
    trace_url: str | None = None
    goal: SessionGoal | None = None
    goal_transition: GoalTransition | None = None
