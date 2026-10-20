"""Continuation and Tool policy facade with lazy plugin exports."""

from sagents.v2._lazy import exported_names, resolve_export


_CONTINUATION = "sagents.v2.agent.policy.continuation"
_JUDGE = "sagents.v2.agent.policy.plugins.judge"
_SELF_CHECK = "sagents.v2.agent.policy.output_self_check"
_TOOL = "sagents.v2.agent.policy.tool_policy"
_APPROVAL_MEMORY = "sagents.v2.agent.policy.approval_memory"
_CONTINUATION_PLUGINS = "sagents.v2.agent.policy.plugins.continuation"
_CONTINUATION_RULES = "sagents.v2.agent.policy.plugins._shared.continuation_rules"
_TOOL_PLUGIN = "sagents.v2.agent.policy.plugins.tool_policy"
_APPROVAL_MEMORY_PLUGIN = "sagents.v2.agent.policy.plugins.approval_memory"
_EXPORTS = {
    "OutputCheck": (_SELF_CHECK, "OutputCheck"),
    "OutputChecker": (_SELF_CHECK, "OutputChecker"),
    "OutputSelfCheck": (_SELF_CHECK, "OutputSelfCheck"),
    "OutputSelfCheckPolicy": (_SELF_CHECK, "OutputSelfCheckPolicy"),
    "ApprovalMatcher": (_TOOL, "ApprovalMatcher"),
    "ApprovalMemory": (_APPROVAL_MEMORY, "ApprovalMemory"),
    "ToolApprovalConfig": (
        "sagents.v2.agent.policy.approval_config",
        "ToolApprovalConfig",
    ),
    "ApprovalStrategy": (_TOOL, "ApprovalStrategy"),
    "BudgetRule": (_CONTINUATION_RULES, "BudgetRule"),
    "CompositeContinuationPolicy": (_CONTINUATION_PLUGINS, "CompositeContinuationPolicy"),
    "ContinuationAction": (_CONTINUATION, "ContinuationAction"),
    "ContinuationContext": (_CONTINUATION, "ContinuationContext"),
    "ContinuationDecision": (_CONTINUATION, "ContinuationDecision"),
    "ContinuationPolicy": (_CONTINUATION, "ContinuationPolicy"),
    "ContinuationSignalProvider": (_CONTINUATION, "ContinuationSignalProvider"),
    "ContinuationSignals": (_CONTINUATION, "ContinuationSignals"),
    "DefaultToolPolicy": (_TOOL_PLUGIN, "DefaultToolPolicy"),
    "ExplicitStatusContinuationPolicy": (
        _CONTINUATION_PLUGINS,
        "ExplicitStatusContinuationPolicy",
    ),
    "ExplicitStatusRequiredRule": (_CONTINUATION_RULES, "ExplicitStatusRequiredRule"),
    "ExplicitStatusRule": (_CONTINUATION_RULES, "ExplicitStatusRule"),
    "FlowBoundaryRule": (_CONTINUATION_RULES, "FlowBoundaryRule"),
    "HybridContinuationPolicy": (_JUDGE, "HybridContinuationPolicy"),
    "InteractionDraft": (_CONTINUATION, "InteractionDraft"),
    "JudgeVerdict": (_JUDGE, "JudgeVerdict"),
    "LLMContinuationJudge": (_JUDGE, "LLMContinuationJudge"),
    "LLMJudgeContinuationPolicy": (_JUDGE, "LLMJudgeContinuationPolicy"),
    "LoopRecoveryRule": (_CONTINUATION_RULES, "LoopRecoveryRule"),
    "RememberedApproval": (_APPROVAL_MEMORY, "RememberedApproval"),
    "SessionApprovalMemory": (_APPROVAL_MEMORY_PLUGIN, "SessionApprovalMemory"),
    "ToolOperationAssessment": (_TOOL, "ToolOperationAssessment"),
    "ToolOrTextRule": (_CONTINUATION_RULES, "ToolOrTextRule"),
    "ToolOrTextRuleForPendingCalls": (_CONTINUATION_RULES, "ToolOrTextRuleForPendingCalls"),
    "ToolPolicyAction": (_TOOL, "ToolPolicyAction"),
    "ToolPolicyContext": (_TOOL, "ToolPolicyContext"),
    "ToolPolicyDecision": (_TOOL, "ToolPolicyDecision"),
    "exact_arguments_matcher": (_TOOL_PLUGIN, "exact_arguments_matcher"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
