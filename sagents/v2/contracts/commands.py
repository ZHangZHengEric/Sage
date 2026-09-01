"""SAgents V2 module for contracts/commands.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, SkillName, StrictModel, ToolName
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import ContentBlock
from sagents.v2.contracts.run_state import SessionConcurrencyMode


class CommandDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class InputItem(StrictModel):
    # A new Run may carry an already-rendered conversation ledger. Tool rows are
    # deliberately excluded: only the Kernel may create trusted tool results.
    role: Literal["user", "assistant", "system", "developer"]
    content: tuple[ContentBlock, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunConfig(StrictModel):
    """Per-Run overrides already narrowed against the Agent policy ceiling."""

    model_bindings: dict[str, str] = Field(default_factory=dict)
    # ``None`` means that a compatibility host did not provide a per-Run grant
    # and the resolved Agent defaults apply.  An empty tuple is an explicit
    # least-privilege grant of no Tools/Skills.
    enabled_tools: tuple[ToolName, ...] | None = None
    enabled_skills: tuple[SkillName, ...] | None = None
    max_steps: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)
    deadline_seconds: float | None = Field(default=None, gt=0)
    flow_boundary: Literal["complete_node", "continue_node"] | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartRun(StrictModel):
    """Request one execution in a new, existing, or forked Session.

    `session_id` selects the context container; it is not the execution id. The
    SessionStore returns a new `run_id` unless this is an idempotent duplicate of
    the same StartRun request.
    """

    session_id: Identifier | None = None
    agent_id: Identifier
    input: tuple[InputItem, ...]
    config: RunConfig = Field(default_factory=RunConfig)
    session_concurrency_mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL
    base_session_revision: int | None = Field(default=None, ge=0)
    resolved_spec_hash: str
    idempotency_key: Identifier
    parent_run_id: Identifier | None = None
    invocation_mode: str | None = None

    @model_validator(mode="after")
    def validate_fork(self) -> "StartRun":
        if (
            self.session_concurrency_mode == SessionConcurrencyMode.FORK
            and self.session_id is None
        ):
            raise ValueError("fork mode requires a parent session_id")
        return self


class RunCommand(StrictModel):
    """Base for commands that mutate an existing Run with optimistic CAS."""

    run_id: Identifier
    idempotency_key: Identifier
    expected_revision: int = Field(ge=0)


class PauseRun(RunCommand):
    reason: str = "user_requested"


class ResumeRun(RunCommand):
    suspension_id: Identifier
    expected_suspension_revision: int = Field(ge=0)


class CancelRun(RunCommand):
    reason: str = "user_requested"


class SteerRun(RunCommand):
    """Queue model-visible input for the next safe Step of the active Turn."""

    expected_turn_id: Identifier
    input: tuple[InputItem, ...]
    mode: str = "queue_next_step"


class SteerInboxStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"


class SteerInboxEntry(StrictModel):
    steer_id: Identifier
    run_id: Identifier
    expected_turn_id: Identifier
    inbox_sequence: int = Field(ge=1)
    input: tuple[InputItem, ...]
    mode: str
    status: SteerInboxStatus = SteerInboxStatus.PENDING
    created_at: datetime
    applied_at: datetime | None = None


class ReplyInteraction(RunCommand):
    """Resolve a persisted runtime request, not create a conversational Run."""

    suspension_id: Identifier
    interaction_id: Identifier
    expected_suspension_revision: int = Field(ge=0)
    expected_interaction_revision: int = Field(ge=0)
    decision: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandReceipt(StrictModel):
    """Immediate command acceptance; later execution facts arrive as events."""

    command_id: Identifier
    decision: CommandDecision
    target_id: Identifier | None = None
    current_revision: int | None = Field(default=None, ge=0)
    result: dict[str, Any] | None = None
    error: RuntimeErrorInfo | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "CommandReceipt":
        if self.decision == CommandDecision.REJECTED and self.error is None:
            raise ValueError("rejected command requires error")
        if self.decision != CommandDecision.REJECTED and self.error is not None:
            raise ValueError("accepted or duplicate command cannot contain error")
        return self
