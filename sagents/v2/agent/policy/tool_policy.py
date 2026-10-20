"""Tool authorization inputs, decisions and approval matching contracts."""

from __future__ import annotations

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
    """ "记住审批"时保存的精确匹配器：工具名 + 规范化参数指纹。

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
