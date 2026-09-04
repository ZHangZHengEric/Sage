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
    invocation_mode: str | None = None


class ApprovalMatcher(StrictModel):
    """"记住审批"时保存的精确匹配器：工具名 + 规范化参数指纹。

    只保存宿主能解释、用户能看懂的精确匹配，不保存内部 risk category，
    以免策略升级后旧的记忆意外放宽。
    """

    tool_name: str
    fingerprint: str
    summary: str

    @property
    def key(self) -> str:
        return f"{self.tool_name}:{self.fingerprint}"


class ToolPolicyDecision(StrictModel):
    action: ToolPolicyAction
    decision_id: Identifier
    policy_version: str
    policy_hash: str
    reason: str
    allowed_decisions: tuple[str, ...] = ()
    interaction_payload: dict = Field(default_factory=dict)
    # 该决定是否允许被审批记忆满足/写入；匹配器由策略给出，记忆由 Loop 持有。
    persistent_approval_allowed: bool = False
    approval_matcher: ApprovalMatcher | None = None


class ToolOperationAssessment(StrictModel):
    """Call-specific policy result supplied by a concrete composition root."""

    action: ToolPolicyAction
    reason: str
    category: str | None = None
    side_effect_level: SideEffectLevel | None = None
    persistent_approval_allowed: bool = False


ApprovalMatcherBuilder = Callable[[ToolPolicyContext], ApprovalMatcher | None]

EXACT_ARGUMENTS_MATCHER_ID = "sage.approval-matcher.exact-arguments/v1"
_MATCHER_SUMMARY_LIMIT = 160


def exact_arguments_matcher(context: ToolPolicyContext) -> ApprovalMatcher:
    """默认匹配器：工具名 + 全部参数的规范化 JSON 指纹，只匹配完全相同的调用。

    宿主可以换成更宽的匹配（如 shell 命令前缀、文件路径），但那是产品策略，
    不在 Kernel 内写死。
    """

    encoded = json.dumps(
        context.call.arguments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    summary = f"{context.definition.name} {encoded}"
    if len(summary) > _MATCHER_SUMMARY_LIMIT:
        summary = summary[: _MATCHER_SUMMARY_LIMIT - 1] + "…"
    return ApprovalMatcher(
        tool_name=context.definition.name,
        fingerprint=f"sha256:{digest}",
        summary=summary,
    )


class DefaultToolPolicy:
    """Combine actor scopes, tool metadata, and host risk assessment.

    A decision is stable and auditable through `policy_hash`/`decision_id`. The
    policy requests an Interaction but never performs the Tool call itself.

    审批记忆的分工：策略只回答"这次调用允许被记住吗、按什么匹配器记"
    （`persistent_approval_allowed` / `approval_matcher`），记忆本身由 Loop
    持有的 `ApprovalMemory` 读写；没有记忆端口时这两个字段没有任何效果。
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
        allow_persistent_approval: bool = False,
        approval_matcher: ApprovalMatcherBuilder | None = None,
        approval_matcher_id: str | None = None,
    ) -> None:
        self.policy_version = policy_version
        self.approval_strategy = approval_strategy
        self.operation_assessor = operation_assessor
        self.operation_assessor_id = operation_assessor_id
        # 无 assessor 时是否允许"记住审批"；有 assessor 时以其逐次判断为准。
        # ALWAYS_ASK 下永远不允许：那是用户明确要求每次都问。
        self.allow_persistent_approval = allow_persistent_approval
        self.approval_matcher = approval_matcher or exact_arguments_matcher
        self.approval_matcher_id = (
            approval_matcher_id
            if approval_matcher is not None
            else EXACT_ARGUMENTS_MATCHER_ID
        )
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
                "allow_persistent_approval": allow_persistent_approval,
                "approval_matcher_id": self.approval_matcher_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.policy_hash = f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def composition_identity(self) -> str:
        """宿主直接注入时，让组合身份（composition hash）纳入策略本身。"""

        return self.policy_hash

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
        if (
            context.invocation_mode == "plan"
            and context.definition.side_effect_level
            not in {SideEffectLevel.NONE, SideEffectLevel.READ}
            and not context.definition.plan_safe
            # Backward-compatible identity for hosts that construct the
            # built-in control definition without the newer plan_safe field.
            and context.definition.name != "goal_submit"
        ):
            return ToolPolicyDecision(
                action=ToolPolicyAction.DENY,
                decision_id=decision_id,
                policy_version=self.policy_version,
                policy_hash=self.policy_hash,
                reason="Plan mode forbids tools with external side effects",
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
        if self._requires_interaction(context, assessment):
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
            allowed_decisions = ["approve_once"]
            if assessment is not None and assessment.persistent_approval_allowed:
                # 宿主 assessor 明确允许：沿用既有行为，由宿主自行落地记忆。
                allowed_decisions.append("approve_and_remember")
                interaction_payload["persistent_approval_allowed"] = True
            allowed_decisions.extend(("deny", "cancel"))
            matcher = self._persistent_approval_matcher(context, assessment)
            if matcher is not None:
                interaction_payload["approval_matcher"] = matcher.model_dump(
                    mode="json"
                )
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
                allowed_decisions=tuple(allowed_decisions),
                interaction_payload=interaction_payload,
                persistent_approval_allowed=matcher is not None,
                approval_matcher=matcher,
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

    def _persistent_approval_matcher(
        self,
        context: ToolPolicyContext,
        assessment: ToolOperationAssessment | None,
    ) -> ApprovalMatcher | None:
        """本次调用允许被记住时返回匹配器；返回 None 表示只能 approve_once。"""

        if self.approval_strategy == ApprovalStrategy.ALWAYS_ASK:
            return None
        allowed = (
            assessment.persistent_approval_allowed
            if assessment is not None
            else self.allow_persistent_approval
        )
        if not allowed:
            return None
        return self.approval_matcher(context)

    def _requires_interaction(
        self,
        context: ToolPolicyContext,
        assessment: ToolOperationAssessment | None,
    ) -> bool:
        definition = context.definition
        if context.invocation_mode == "plan" and definition.name == "goal_submit":
            return True
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
