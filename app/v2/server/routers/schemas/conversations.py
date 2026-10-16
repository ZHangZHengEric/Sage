from __future__ import annotations

from typing import Any
from ag_ui.core import RunAgentInput
from pydantic import BaseModel, Field, model_validator

from app.v2.server.conversations.agui.mapping import resolve_session_id
from sagents.v2.contracts.errors import SageV2Error

class AgentRunBody(BaseModel):
    session_id: str | None = None
    threadId: str | None = None
    runId: str
    messages: list
    state: dict = Field(default_factory=dict)
    tools: list = Field(default_factory=list)
    context: list = Field(default_factory=list)
    forwardedProps: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_session(self):
        try:
            self.session_id = resolve_session_id(self.session_id, self.threadId)
        except SageV2Error:
            raise
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        self.threadId = self.session_id
        return self

    def to_agui(self) -> RunAgentInput:
        return RunAgentInput.model_validate(self.model_dump(exclude={"session_id"}))

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

    has_package: bool = False
    events: list[dict[str, Any]]
    total: int
    offset: int
    limit: int

