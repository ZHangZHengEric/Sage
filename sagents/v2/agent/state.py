"""Serializable working state for pausing and resuming the Agent Loop."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

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
    pending_tool_result: dict | None = None
    pending_child_interactions: tuple[dict, ...] = ()
    retry_model_step: bool = False
    # V1 LLM-Judge continuation requires the next direct model response to use
    # a Tool and injects the Judge reason only into that inference request.
    force_tool_choice_required_next: bool = False
    pending_continuation_reason: str | None = None
    # A Flow boundary is a one-shot host signal. It remains checkpointed while
    # tools run or the Run is suspended, then is consumed by FlowBoundaryRule.
    pending_flow_boundary: Literal["complete_node", "continue_node"] | None = None
    # Run-scoped Tool projection state. Persisting exact names makes
    # tool_expand_tools survive suspension and process restart.
    expanded_tool_names: tuple[str, ...] = ()
    # Stable response fingerprints allow ContinuationPolicy to detect a loop
    # without depending on provider-specific text formatting.
    response_fingerprints: tuple[str, ...] = ()
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)


class PendingToolPhase(str, Enum):
    APPROVAL = "approval"
    DELEGATION_INTERACTION = "delegation_interaction"
    RECONCILIATION = "reconciliation"


class NoPendingBarrier(StrictModel):
    kind: Literal["none"] = "none"


class ModelRetryBarrier(StrictModel):
    kind: Literal["model_retry"] = "model_retry"


class ToolBarrierState(StrictModel):
    kind: Literal["tool"] = "tool"
    call: ToolCall
    policy: ToolPolicyDecision | None = None
    phase: PendingToolPhase | None = None
    step_id: Identifier | None = None
    error: dict | None = None
    result: dict | None = None
    child_interactions: tuple[dict, ...] = ()


PendingBarrierState = Annotated[
    NoPendingBarrier | ModelRetryBarrier | ToolBarrierState,
    Field(discriminator="kind"),
]
_PENDING_ADAPTER = TypeAdapter(PendingBarrierState)


class AgentLoopCheckpointCodec:
    """Encode v3 discriminated barriers and read legacy flat checkpoints."""

    version = "agent-loop/3"

    @staticmethod
    def encode(state: AgentLoopCheckpointState, *, ledger_digest: str) -> dict:
        payload = state.model_dump(
            mode="json",
            exclude={
                "messages",
                "pending_tool_call",
                "pending_tool_policy",
                "pending_tool_phase",
                "pending_tool_step_id",
                "pending_tool_error",
                "pending_tool_result",
                "pending_child_interactions",
                "retry_model_step",
            },
        )
        payload["state_version"] = "3"
        payload["ledger_digest"] = ledger_digest
        if state.pending_tool_call is not None:
            pending: PendingBarrierState = ToolBarrierState(
                call=state.pending_tool_call,
                policy=state.pending_tool_policy,
                phase=(
                    PendingToolPhase(state.pending_tool_phase)
                    if state.pending_tool_phase is not None
                    else None
                ),
                step_id=state.pending_tool_step_id,
                error=state.pending_tool_error,
                result=state.pending_tool_result,
                child_interactions=state.pending_child_interactions,
            )
        elif state.retry_model_step:
            pending = ModelRetryBarrier()
        else:
            pending = NoPendingBarrier()
        payload["pending"] = pending.model_dump(mode="json")
        return payload

    @staticmethod
    def decode(payload: dict) -> AgentLoopCheckpointState:
        if str(payload.get("state_version") or "1") != "3":
            return AgentLoopCheckpointState.model_validate(payload)
        pending = _PENDING_ADAPTER.validate_python(payload.get("pending", {"kind": "none"}))
        flattened = {key: value for key, value in payload.items() if key != "pending"}
        if isinstance(pending, ToolBarrierState):
            flattened.update(
                {
                    "pending_tool_call": pending.call,
                    "pending_tool_policy": pending.policy,
                    "pending_tool_phase": (
                        pending.phase.value if pending.phase is not None else None
                    ),
                    "pending_tool_step_id": pending.step_id,
                    "pending_tool_error": pending.error,
                    "pending_tool_result": pending.result,
                    "pending_child_interactions": pending.child_interactions,
                }
            )
        elif isinstance(pending, ModelRetryBarrier):
            flattened["retry_model_step"] = True
        return AgentLoopCheckpointState.model_validate(flattened)


__all__ = [
    "AgentLoopCheckpointCodec",
    "AgentLoopCheckpointState",
    "ModelRetryBarrier",
    "NoPendingBarrier",
    "PendingBarrierState",
    "PendingToolPhase",
    "ToolBarrierState",
]
