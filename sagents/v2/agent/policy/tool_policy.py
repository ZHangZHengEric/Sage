"""Authorize a specific ToolCall before the executor crosses a side effect."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from enum import Enum

from pydantic import Field

from sagents.v2.tool.contracts import (
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
)
from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.principals import ActorRef


class ToolPolicyAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_INTERACTION = "require_interaction"


class ApprovalStrategy(str, Enum):
    CONFIGURED = "configured"
    ALWAYS_ASK = "always_ask"
    HIGH_RISK = "high_risk"
    AUTO_APPROVE = "auto_approve"


class ToolPolicyContext(StrictModel):
    run_id: Identifier
    actor: ActorRef
    definition: ToolDefinition
    call: ToolCall


class ToolPolicyDecision(StrictModel):
    action: ToolPolicyAction
    decision_id: Identifier
    policy_version: str
    policy_hash: str
    reason: str
    allowed_decisions: tuple[str, ...] = ()
    interaction_payload: dict = Field(default_factory=dict)


class ToolOperationAssessment(StrictModel):
    """Call-specific policy result supplied by a concrete composition root."""

    action: ToolPolicyAction
    reason: str
    category: str | None = None
    side_effect_level: SideEffectLevel | None = None


class DefaultToolPolicy:
    """Combine actor scopes, tool metadata, and host risk assessment.

    A decision is stable and auditable through `policy_hash`/`decision_id`. The
    policy requests an Interaction but never performs the Tool call itself.
    """

    def __init__(
        self,
        *,
        policy_version: str = "1",
        approval_levels: frozenset[SideEffectLevel] | None = None,
        approval_strategy: ApprovalStrategy = ApprovalStrategy.CONFIGURED,
        operation_assessor: (
            Callable[[ToolPolicyContext], ToolOperationAssessment | None] | None
        ) = None,
        operation_assessor_id: str | None = None,
    ) -> None:
        self.policy_version = policy_version
        self.approval_strategy = approval_strategy
        self.operation_assessor = operation_assessor
        self.operation_assessor_id = operation_assessor_id
        self.approval_levels = (
            approval_levels
            if approval_levels is not None
            else frozenset(
                {
                    SideEffectLevel.WRITE,
                    SideEffectLevel.REVERSIBLE,
                    SideEffectLevel.IRREVERSIBLE,
                }
            )
        )
        encoded = json.dumps(
            {
                "version": policy_version,
                "approval_strategy": approval_strategy.value,
                "approval_levels": sorted(
                    value.value for value in self.approval_levels
                ),
                "operation_assessor_id": operation_assessor_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.policy_hash = f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    async def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision:
        missing_scopes = sorted(
            set(context.definition.required_scopes) - set(context.actor.scopes)
        )
        seed = f"{context.run_id}:{context.call.tool_call_id}:{self.policy_hash}"
        decision_id = f"decision_{hashlib.sha256(seed.encode()).hexdigest()[:24]}"
        if missing_scopes:
            return ToolPolicyDecision(
                action=ToolPolicyAction.DENY,
                decision_id=decision_id,
                policy_version=self.policy_version,
                policy_hash=self.policy_hash,
                reason=f"actor lacks required scopes: {missing_scopes}",
            )
        assessment = (
            self.operation_assessor(context)
            if self.operation_assessor is not None
            else None
        )
        if assessment is not None and assessment.action == ToolPolicyAction.DENY:
            return ToolPolicyDecision(
                action=ToolPolicyAction.DENY,
                decision_id=decision_id,
                policy_version=self.policy_version,
                policy_hash=self.policy_hash,
                reason=assessment.reason,
            )
        if self._requires_interaction(context.definition, assessment):
            risk_level = (
                assessment.side_effect_level
                if assessment is not None and assessment.side_effect_level is not None
                else context.definition.side_effect_level
            )
            interaction_payload = {
                "tool_name": context.definition.name,
                "arguments": context.call.arguments,
                "side_effect_level": risk_level.value,
            }
            if assessment is not None:
                interaction_payload["risk_reason"] = assessment.reason
                if assessment.category is not None:
                    interaction_payload["risk_category"] = assessment.category
            return ToolPolicyDecision(
                action=ToolPolicyAction.REQUIRE_INTERACTION,
                decision_id=decision_id,
                policy_version=self.policy_version,
                policy_hash=self.policy_hash,
                reason=(
                    assessment.reason
                    if assessment is not None
                    else "tool side effect requires approval"
                ),
                allowed_decisions=("approve_once", "deny", "cancel"),
                interaction_payload=interaction_payload,
            )
        return ToolPolicyDecision(
            action=ToolPolicyAction.ALLOW,
            decision_id=decision_id,
            policy_version=self.policy_version,
            policy_hash=self.policy_hash,
            reason=(
                assessment.reason
                if assessment is not None
                else "tool is allowed by policy"
            ),
        )

    def _requires_interaction(
        self,
        definition: ToolDefinition,
        assessment: ToolOperationAssessment | None,
    ) -> bool:
        if self.approval_strategy == ApprovalStrategy.ALWAYS_ASK:
            return True
        if self.approval_strategy == ApprovalStrategy.HIGH_RISK:
            if assessment is not None:
                return assessment.action == ToolPolicyAction.REQUIRE_INTERACTION
            return definition.requires_approval or (
                definition.side_effect_level == SideEffectLevel.IRREVERSIBLE
            )
        if self.approval_strategy == ApprovalStrategy.AUTO_APPROVE:
            return False
        if assessment is not None:
            return assessment.action == ToolPolicyAction.REQUIRE_INTERACTION
        return (
            definition.requires_approval
            or definition.side_effect_level in self.approval_levels
        )
