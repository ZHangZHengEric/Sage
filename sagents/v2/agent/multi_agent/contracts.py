"""Typed child-Agent invocation contracts built on ordinary Sessions and Runs."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Protocol

from pydantic import model_validator

from sagents.v2.contracts.common import Identifier, SkillName, StrictModel, ToolName
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import ContentBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState


class AgentMode(str, Enum):
    SIMPLE = "simple"
    FIBRE = "fibre"
    TEAM = "team"
    FLOW = "flow"


class AgentInvocationMode(str, Enum):
    """Who owns control after invoking another Agent."""

    AGENT_AS_TOOL = "agent_as_tool"
    HANDOFF = "handoff"
    DELEGATION = "delegation"


class WorkspaceSharingPolicy(str, Enum):
    """Explicit filesystem relationship between parent and child execution."""

    PRIVATE_CHILD = "private_child"
    SHARED_PARENT = "shared_parent"
    READ_ONLY_PARENT = "read_only_parent"


class AgentDescriptor(StrictModel):
    agent_id: Identifier
    name: str
    description: str
    instructions: str
    mode: AgentMode = AgentMode.SIMPLE
    tools: tuple[ToolName, ...] = ()
    skills: tuple[SkillName, ...] = ()
    dynamic: bool = False
    # A persistent Fibre/Team Agent may be selected as a member while executing
    # as a leaf for this invocation.  Keep its declared mode visible instead of
    # silently rewriting it to SIMPLE.
    allow_delegation: bool = True


class DelegationTask(StrictModel):
    task_id: Identifier
    agent_id: Identifier
    task_name: str
    original_task: str
    content: str
    parent_tool_call_id: Identifier | None = None
    child_session_id: Identifier | None = None
    flow_boundary: Literal["complete_node", "continue_node"] | None = None
    invocation_mode: AgentInvocationMode = AgentInvocationMode.DELEGATION


class DelegationBatch(StrictModel):
    tasks: tuple[DelegationTask, ...]

    @model_validator(mode="after")
    def validate_sessions(self) -> "DelegationBatch":
        explicit = [
            task.child_session_id for task in self.tasks if task.child_session_id
        ]
        if len(explicit) != len(set(explicit)):
            raise ValueError(
                "parallel delegation tasks require distinct child_session_id values"
            )
        return self


class DelegationResult(StrictModel):
    task_id: Identifier
    agent_id: Identifier
    child_session_id: Identifier
    child_run_id: Identifier
    outcome: RunState
    content: tuple[ContentBlock, ...] = ()
    error: RuntimeErrorInfo | None = None


class ChildRunExecutor(Protocol):
    async def run_child(
        self,
        descriptor: AgentDescriptor,
        task: DelegationTask,
        *,
        parent_run_id: str,
        workspace_policy: WorkspaceSharingPolicy,
        context: RequestContext,
    ) -> DelegationResult: ...
