"""Serializable working state for pausing and resuming the Agent Loop."""

from __future__ import annotations

from pydantic import Field

from sagents.v2.model.contracts import ModelMessage
from sagents.v2.agent.policy.tool_policy import ToolPolicyDecision
from sagents.v2.tool.contracts import ToolCall
from sagents.v2.contracts.common import Identifier, StrictModel


class AgentLoopCheckpointState(StrictModel):
    """Control state needed to resume without replaying a completed side effect.

    `messages` is live in-process working state only. New checkpoint payloads
    exclude it and store `ledger_digest`; resume reconstructs messages from
    canonical completed Item events and verifies that digest. The optional field
    remains readable solely so pre-v2 checkpoint payloads can be recovered.
    """

    state_version: str = "2"
    turn_id: Identifier
    step_number: int = Field(ge=1)
    messages: tuple[ModelMessage, ...] = ()
    ledger_digest: str | None = None
    pending_tool_call: ToolCall | None = None
    # The following fields form one resumable tool barrier. They identify
    # whether the Run paused before authorization or because the external side
    # effect may have happened but its result is uncertain.
    pending_tool_policy: ToolPolicyDecision | None = None
    pending_tool_phase: str | None = None
    pending_tool_step_id: Identifier | None = None
    pending_tool_error: dict | None = None
    retry_model_step: bool = False
    # Stable response fingerprints allow ContinuationPolicy to detect a loop
    # without depending on provider-specific text formatting.
    response_fingerprints: tuple[str, ...] = ()
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
