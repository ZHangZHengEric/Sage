"""Continuation and Tool policy facade with lazy plugin exports."""

from sagents.v2._lazy import exported_names, resolve_export


_CONTINUATION = "sagents.v2.agent.policy.continuation"
_JUDGE = "sagents.v2.agent.policy.judge"
_TOOL = "sagents.v2.agent.policy.tool_policy"
_APPROVAL_MEMORY = "sagents.v2.agent.policy.approval_memory"
_EXPORTS = {
    "ApprovalMatcher": (_TOOL, "ApprovalMatcher"),
    "ApprovalMemory": (_APPROVAL_MEMORY, "ApprovalMemory"),
    "ApprovalStrategy": (_TOOL, "ApprovalStrategy"),
    "BudgetRule": (_CONTINUATION, "BudgetRule"),
    "CompositeContinuationPolicy": (_CONTINUATION, "CompositeContinuationPolicy"),
    "ContinuationAction": (_CONTINUATION, "ContinuationAction"),
    "ContinuationContext": (_CONTINUATION, "ContinuationContext"),
    "ContinuationDecision": (_CONTINUATION, "ContinuationDecision"),
    "ContinuationPolicy": (_CONTINUATION, "ContinuationPolicy"),
    "ContinuationSignalProvider": (_CONTINUATION, "ContinuationSignalProvider"),
    "ContinuationSignals": (_CONTINUATION, "ContinuationSignals"),
    "DefaultToolPolicy": (_TOOL, "DefaultToolPolicy"),
    "ExplicitStatusContinuationPolicy": (
        _CONTINUATION,
        "ExplicitStatusContinuationPolicy",
    ),
    "ExplicitStatusRequiredRule": (_CONTINUATION, "ExplicitStatusRequiredRule"),
    "ExplicitStatusRule": (_CONTINUATION, "ExplicitStatusRule"),
    "FlowBoundaryRule": (_CONTINUATION, "FlowBoundaryRule"),
    "HybridContinuationPolicy": (_JUDGE, "HybridContinuationPolicy"),
    "InteractionDraft": (_CONTINUATION, "InteractionDraft"),
    "JudgeVerdict": (_JUDGE, "JudgeVerdict"),
    "LLMContinuationJudge": (_JUDGE, "LLMContinuationJudge"),
    "LLMJudgeContinuationPolicy": (_JUDGE, "LLMJudgeContinuationPolicy"),
    "LoopRecoveryRule": (_CONTINUATION, "LoopRecoveryRule"),
    "RememberedApproval": (_APPROVAL_MEMORY, "RememberedApproval"),
    "SessionApprovalMemory": (_APPROVAL_MEMORY, "SessionApprovalMemory"),
    "ToolOperationAssessment": (_TOOL, "ToolOperationAssessment"),
    "ToolOrTextRule": (_CONTINUATION, "ToolOrTextRule"),
    "ToolOrTextRuleForPendingCalls": (_CONTINUATION, "ToolOrTextRuleForPendingCalls"),
    "ToolPolicyAction": (_TOOL, "ToolPolicyAction"),
    "ToolPolicyContext": (_TOOL, "ToolPolicyContext"),
    "ToolPolicyDecision": (_TOOL, "ToolPolicyDecision"),
    "exact_arguments_matcher": (_TOOL, "exact_arguments_matcher"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
