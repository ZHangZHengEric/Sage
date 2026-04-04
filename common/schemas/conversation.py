from pydantic import BaseModel


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
