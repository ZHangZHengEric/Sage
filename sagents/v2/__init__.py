"""Sage Agents v2 public API.

The v2 package is intentionally independent from the legacy runtime.  Importing
it must not initialize global managers, model clients, MCP connections, or app
services. See `sagents/v2/README.md` for the lifecycle model, embedding example,
built-in inventory, and implementation-status boundaries.

Requires Python 3.12 or newer. The legacy Sage runtime remains 3.10+.
"""

from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "ComposedRun": ("sagents.v2.composition.resources", "ComposedRun"),
    "RunResources": ("sagents.v2.composition.resources", "RunResources"),
    "AgentPackageTestGenerator": (
        "sagents.v2.optimization",
        "AgentPackageTestGenerator",
    ),
    "OptimizationSuiteGeneration": (
        "sagents.v2.optimization",
        "OptimizationSuiteGeneration",
    ),
    "AgentPackageOptimizer": ("sagents.v2.optimization", "AgentPackageOptimizer"),
    "IsolatedOptimizationRunner": (
        "sagents.v2.optimization",
        "IsolatedOptimizationRunner",
    ),
    "OptimizationAgent": ("sagents.v2.optimization", "OptimizationAgent"),
    "OptimizationConstraints": ("sagents.v2.optimization", "OptimizationConstraints"),
    "OptimizationCase": ("sagents.v2.optimization", "OptimizationCase"),
    "OptimizationCaseTrial": ("sagents.v2.optimization", "OptimizationCaseTrial"),
    "OptimizationSuiteIssue": ("sagents.v2.optimization", "OptimizationSuiteIssue"),
    "OptimizationSuiteReview": ("sagents.v2.optimization", "OptimizationSuiteReview"),
    "OptimizationSuiteReviewRejected": ("sagents.v2.optimization", "OptimizationSuiteReviewRejected"),
    "OptimizationSuite": ("sagents.v2.optimization", "OptimizationSuite"),
    "OptimizationFinalSuite": ("sagents.v2.optimization", "OptimizationFinalSuite"),
    "OptimizationFinalVerification": (
        "sagents.v2.optimization",
        "OptimizationFinalVerification",
    ),
    "OptimizationProposalReview": (
        "sagents.v2.optimization",
        "OptimizationProposalReview",
    ),
    "OptimizationFinalSuiteGeneration": (
        "sagents.v2.optimization",
        "OptimizationFinalSuiteGeneration",
    ),
    "OptimizationIteration": ("sagents.v2.optimization", "OptimizationIteration"),
    "OptimizationResult": ("sagents.v2.optimization", "OptimizationResult"),
    "OptimizationReport": ("sagents.v2.optimization", "OptimizationReport"),
    "SelfConfigurationService": (
        "sagents.v2.agent.self_configuration",
        "SelfConfigurationService",
    ),
    "SelfConfigurationRequest": (
        "sagents.v2.agent.self_configuration",
        "SelfConfigurationRequest",
    ),
    "SqliteSelfConfigurationStore": (
        "sagents.v2.agent.self_configuration",
        "SqliteSelfConfigurationStore",
    ),
    "AgentManagementService": ("sagents.v2.agent.management", "AgentManagementService"),
    "AgentPackageBundle": ("sagents.v2.agent.management", "AgentPackageBundle"),
    "AgentPackageStore": ("sagents.v2.agent.management", "AgentPackageStore"),
    "ActorRef": ("sagents.v2.contracts", "ActorRef"),
    "EventCursor": ("sagents.v2.contracts", "EventCursor"),
    "ExecutionBindingProvider": (
        "sagents.v2.runtime.execution",
        "ExecutionBindingProvider",
    ),
    "ExecutionBindingRequest": (
        "sagents.v2.runtime.execution",
        "ExecutionBindingRequest",
    ),
    "InterfaceRunStream": ("sagents.v2.application", "InterfaceRunStream"),
    "MaterializedAgentPorts": ("sagents.v2.application", "MaterializedAgentPorts"),
    "ProposeSessionCommit": ("sagents.v2.contracts", "ProposeSessionCommit"),
    "PublishSessionCommit": ("sagents.v2.contracts", "PublishSessionCommit"),
    "RejectSessionCommit": ("sagents.v2.contracts", "RejectSessionCommit"),
    "RequestContext": ("sagents.v2.contracts", "RequestContext"),
    "ResolvedApplicationPlan": (
        "sagents.v2.application",
        "ResolvedApplicationPlan",
    ),
    "ResolvedProviderBinding": (
        "sagents.v2.application",
        "ResolvedProviderBinding",
    ),
    "RunExecutionBinding": ("sagents.v2.runtime.execution", "RunExecutionBinding"),
    "RunHandle": ("sagents.v2.contracts", "RunHandle"),
    "RuntimeEvent": ("sagents.v2.contracts", "RuntimeEvent"),
    "SAgent": ("sagents.v2.sagent", "SAgent"),
    "SAgentApplication": ("sagents.v2.application", "SAgentApplication"),
    "SAgentBuilder": ("sagents.v2.builder", "SAgentBuilder"),
    "SAgentRunStream": ("sagents.v2.sagent", "SAgentRunStream"),
    "SessionCommitProposal": ("sagents.v2.contracts", "SessionCommitProposal"),
    "SessionMergeStrategy": ("sagents.v2.contracts", "SessionMergeStrategy"),
    "StartRun": ("sagents.v2.contracts", "StartRun"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
