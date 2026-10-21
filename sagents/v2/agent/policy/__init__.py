"""Continuation and Tool policy facade with lazy plugin exports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.agent.policy.output_self_check import OutputCheck as OutputCheck
    from sagents.v2.agent.policy.output_self_check import OutputChecker as OutputChecker
    from sagents.v2.agent.policy.output_self_check import OutputSelfCheck as OutputSelfCheck
    from sagents.v2.agent.policy.output_self_check import OutputSelfCheckPolicy as OutputSelfCheckPolicy
    from sagents.v2.agent.policy.tool_policy import ApprovalMatcher as ApprovalMatcher
    from sagents.v2.agent.policy.approval_memory import ApprovalMemory as ApprovalMemory
    from sagents.v2.agent.policy.approval_config import ToolApprovalConfig as ToolApprovalConfig
    from sagents.v2.agent.policy.tool_policy import ApprovalStrategy as ApprovalStrategy
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import BudgetRule as BudgetRule
    from sagents.v2.agent.policy.plugins.continuation import CompositeContinuationPolicy as CompositeContinuationPolicy
    from sagents.v2.agent.policy.continuation import ContinuationAction as ContinuationAction
    from sagents.v2.agent.policy.continuation import ContinuationContext as ContinuationContext
    from sagents.v2.agent.policy.continuation import ContinuationDecision as ContinuationDecision
    from sagents.v2.agent.policy.continuation import ContinuationPolicy as ContinuationPolicy
    from sagents.v2.agent.policy.continuation import ContinuationSignalProvider as ContinuationSignalProvider
    from sagents.v2.agent.policy.continuation import ContinuationSignals as ContinuationSignals
    from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy as DefaultToolPolicy
    from sagents.v2.agent.policy.plugins.continuation import ExplicitStatusContinuationPolicy as ExplicitStatusContinuationPolicy
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import ExplicitStatusRequiredRule as ExplicitStatusRequiredRule
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import ExplicitStatusRule as ExplicitStatusRule
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import FlowBoundaryRule as FlowBoundaryRule
    from sagents.v2.agent.policy.plugins.judge import HybridContinuationPolicy as HybridContinuationPolicy
    from sagents.v2.agent.policy.continuation import InteractionDraft as InteractionDraft
    from sagents.v2.agent.policy.plugins.judge import JudgeVerdict as JudgeVerdict
    from sagents.v2.agent.policy.plugins.judge import LLMContinuationJudge as LLMContinuationJudge
    from sagents.v2.agent.policy.plugins.judge import LLMJudgeContinuationPolicy as LLMJudgeContinuationPolicy
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import LoopRecoveryRule as LoopRecoveryRule
    from sagents.v2.agent.policy.approval_memory import RememberedApproval as RememberedApproval
    from sagents.v2.agent.policy.plugins.approval_memory import SessionApprovalMemory as SessionApprovalMemory
    from sagents.v2.agent.policy.tool_policy import ToolOperationAssessment as ToolOperationAssessment
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import ToolOrTextRule as ToolOrTextRule
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import ToolOrTextRuleForPendingCalls as ToolOrTextRuleForPendingCalls
    from sagents.v2.agent.policy.tool_policy import ToolPolicyAction as ToolPolicyAction
    from sagents.v2.agent.policy.tool_policy import ToolPolicyContext as ToolPolicyContext
    from sagents.v2.agent.policy.tool_policy import ToolPolicyDecision as ToolPolicyDecision
    from sagents.v2.agent.policy.plugins.tool_policy import exact_arguments_matcher as exact_arguments_matcher


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

__all__ = [
    "OutputCheck",
    "OutputChecker",
    "OutputSelfCheck",
    "OutputSelfCheckPolicy",
    "ApprovalMatcher",
    "ApprovalMemory",
    "ToolApprovalConfig",
    "ApprovalStrategy",
    "BudgetRule",
    "CompositeContinuationPolicy",
    "ContinuationAction",
    "ContinuationContext",
    "ContinuationDecision",
    "ContinuationPolicy",
    "ContinuationSignalProvider",
    "ContinuationSignals",
    "DefaultToolPolicy",
    "ExplicitStatusContinuationPolicy",
    "ExplicitStatusRequiredRule",
    "ExplicitStatusRule",
    "FlowBoundaryRule",
    "HybridContinuationPolicy",
    "InteractionDraft",
    "JudgeVerdict",
    "LLMContinuationJudge",
    "LLMJudgeContinuationPolicy",
    "LoopRecoveryRule",
    "RememberedApproval",
    "SessionApprovalMemory",
    "ToolOperationAssessment",
    "ToolOrTextRule",
    "ToolOrTextRuleForPendingCalls",
    "ToolPolicyAction",
    "ToolPolicyContext",
    "ToolPolicyDecision",
    "exact_arguments_matcher",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
