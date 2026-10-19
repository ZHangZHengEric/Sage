from __future__ import annotations

from app.v2.server.routers.schemas.catalog import AgentSummary, ModelPublic, McpPublic, A2AAgentPublic
from app.v2.server.routers.schemas.skills import SkillPublic
from app.v2.server.routers.schemas.conversations import ThreadPublic

class AdminThreadPublic(ThreadPublic):
    username: str

class AdminModelPublic(ModelPublic):
    user_id: str
    username: str

class AdminAgentSummary(AgentSummary):
    user_id: str
    username: str

class AdminMcpPublic(McpPublic):
    user_id: str
    username: str

class AdminA2AAgentPublic(A2AAgentPublic):
    user_id: str
    username: str

class AdminSkillPublic(SkillPublic):
    user_id: str
    username: str

