from __future__ import annotations

from typing import Any
from ag_ui.core import RunAgentInput
from pydantic import BaseModel, Field

class AgentRunBody(BaseModel):
    threadId: str
    runId: str
    messages: list
    state: dict = Field(default_factory=dict)
    tools: list = Field(default_factory=list)
    context: list = Field(default_factory=list)
    forwardedProps: dict = Field(default_factory=dict)

    def to_agui(self) -> RunAgentInput:
        return RunAgentInput.model_validate(self.model_dump())

class ThreadResumeBody(BaseModel):
    """One answer to the question a thread is waiting on.

    There is no ``threadId``/``runId`` pair identifying the *suspended* Run: the
    thread already knows which of its Runs is waiting, and letting a client name
    it would let a stale tab answer a question that has since been resolved.
    ``runId`` names the AG-UI run identity of the stream this starts, which is
    the client's to choose exactly as it is when starting a Run.
    """

    runId: str
    decision: str
    payload: dict = Field(default_factory=dict)

class ThreadPublic(BaseModel):
    thread_id: str
    user_id: str
    title: str
    agent_id: str = ""
    updated_at: str

class ThreadEventPage(BaseModel):
    """One bounded window of AG-UI frames plus the source event count."""

    events: list[dict[str, Any]]
    total: int
    offset: int
    limit: int

