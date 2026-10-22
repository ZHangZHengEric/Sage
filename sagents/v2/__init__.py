"""Sage Agents v2 public API.

The v2 package is intentionally independent from the legacy runtime.  Importing
it must not initialize global managers, model clients, MCP connections, or app
services. See `sagents/v2/README.md` for the lifecycle model, embedding example,
built-in inventory, and implementation-status boundaries.

Requires Python 3.12 or newer. The legacy Sage runtime remains 3.10+.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.package.manifest.runtime import RuntimeConfig as RuntimeConfig
    from sagents.v2.package.manifest.runtime import SkillModulesConfig as SkillModulesConfig
    from sagents.v2.package.manifest.runtime import SkillUsageConfig as SkillUsageConfig
    from sagents.v2.composition.defaults import default_runtime as default_runtime
    from sagents.v2.composition.loaded_agents import LoadedAgent as LoadedAgent
    from sagents.v2.composition.loaded_agents import StartupRecoveryIssue as StartupRecoveryIssue
    from sagents.v2.optimization import AgentPackageTestGenerator as AgentPackageTestGenerator
    from sagents.v2.optimization import OptimizationSuiteGeneration as OptimizationSuiteGeneration
    from sagents.v2.optimization import AgentPackageOptimizer as AgentPackageOptimizer
    from sagents.v2.optimization import IsolatedOptimizationRunner as IsolatedOptimizationRunner
    from sagents.v2.optimization import OptimizationAgent as OptimizationAgent
    from sagents.v2.optimization import OptimizationConstraints as OptimizationConstraints
    from sagents.v2.optimization import OptimizationCase as OptimizationCase
    from sagents.v2.optimization import OptimizationCaseTrial as OptimizationCaseTrial
    from sagents.v2.optimization import OptimizationSuiteIssue as OptimizationSuiteIssue
    from sagents.v2.optimization import OptimizationSuiteReview as OptimizationSuiteReview
    from sagents.v2.optimization import OptimizationSuiteReviewRejected as OptimizationSuiteReviewRejected
    from sagents.v2.optimization import OptimizationSuite as OptimizationSuite
    from sagents.v2.optimization import OptimizationFinalSuite as OptimizationFinalSuite
    from sagents.v2.optimization import OptimizationFinalVerification as OptimizationFinalVerification
    from sagents.v2.optimization import OptimizationProposalReview as OptimizationProposalReview
    from sagents.v2.optimization import OptimizationFinalSuiteGeneration as OptimizationFinalSuiteGeneration
    from sagents.v2.optimization import OptimizationIteration as OptimizationIteration
    from sagents.v2.optimization import OptimizationResult as OptimizationResult
    from sagents.v2.optimization import OptimizationReport as OptimizationReport
    from sagents.v2.agent.self_configuration import SelfConfigurationService as SelfConfigurationService
    from sagents.v2.agent.self_configuration import SelfConfigurationRequest as SelfConfigurationRequest
    from sagents.v2.agent.self_configuration import SqliteSelfConfigurationStore as SqliteSelfConfigurationStore
    from sagents.v2.agent.management import AgentManagementService as AgentManagementService
    from sagents.v2.agent.management import AgentPackageBundle as AgentPackageBundle
    from sagents.v2.agent.management import AgentPackageStore as AgentPackageStore
    from sagents.v2.contracts import ActorRef as ActorRef
    from sagents.v2.contracts import EventCursor as EventCursor
    from sagents.v2.runtime.execution import ExecutionBindingProvider as ExecutionBindingProvider
    from sagents.v2.runtime.execution import ExecutionBindingRequest as ExecutionBindingRequest
    from sagents.v2.application import InterfaceRunStream as InterfaceRunStream
    from sagents.v2.contracts import ProposeSessionCommit as ProposeSessionCommit
    from sagents.v2.contracts import PublishSessionCommit as PublishSessionCommit
    from sagents.v2.contracts import RejectSessionCommit as RejectSessionCommit
    from sagents.v2.contracts import RequestContext as RequestContext
    from sagents.v2.application import ResolvedApplicationPlan as ResolvedApplicationPlan
    from sagents.v2.application import ResolvedProviderBinding as ResolvedProviderBinding
    from sagents.v2.runtime.execution import RunExecutionBinding as RunExecutionBinding
    from sagents.v2.contracts import RunHandle as RunHandle
    from sagents.v2.contracts import RuntimeEvent as RuntimeEvent
    from sagents.v2.sagent import SAgent as SAgent
    from sagents.v2.application import SAgentApplication as SAgentApplication
    from sagents.v2.model.catalog import ModelCatalogConfig as ModelCatalogConfig
    from sagents.v2.composition.configuration import ApplicationConfiguration as ApplicationConfiguration
    from sagents.v2.builder import SAgentBuilder as SAgentBuilder
    from sagents.v2.sagent import SAgentRunStream as SAgentRunStream
    from sagents.v2.contracts import SessionCommitProposal as SessionCommitProposal
    from sagents.v2.contracts import SessionMergeStrategy as SessionMergeStrategy
    from sagents.v2.contracts import StartRun as StartRun


from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "RuntimeConfig": ("sagents.v2.package.manifest.runtime", "RuntimeConfig"),
    "SkillModulesConfig": ("sagents.v2.package.manifest.runtime", "SkillModulesConfig"),
    "SkillUsageConfig": ("sagents.v2.package.manifest.runtime", "SkillUsageConfig"),
    "default_runtime": ("sagents.v2.composition.defaults", "default_runtime"),
    "LoadedAgent": ("sagents.v2.composition.loaded_agents", "LoadedAgent"),
    "StartupRecoveryIssue": (
        "sagents.v2.composition.loaded_agents",
        "StartupRecoveryIssue",
    ),
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
    "OptimizationRegression": ("sagents.v2.optimization", "OptimizationRegression"),
    "OptimizationCaseTrial": ("sagents.v2.optimization", "OptimizationCaseTrial"),
    "OptimizationSuiteIssue": ("sagents.v2.optimization", "OptimizationSuiteIssue"),
    "OptimizationSuiteReview": ("sagents.v2.optimization", "OptimizationSuiteReview"),
    "OptimizationSuiteReviewRejected": (
        "sagents.v2.optimization",
        "OptimizationSuiteReviewRejected",
    ),
    "HumanTestObserver": ("sagents.v2.optimization", "HumanTestObserver"),
    "IsolatedTestEvaluator": ("sagents.v2.optimization", "IsolatedTestEvaluator"),
    "OptimizationTestSuite": ("sagents.v2.optimization", "OptimizationTestSuite"),
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
    "OptimizationCaseBatch": ("sagents.v2.optimization", "OptimizationCaseBatch"),
    "OptimizationCaseBatchGeneration": (
        "sagents.v2.optimization",
        "OptimizationCaseBatchGeneration",
    ),
    "OptimizationTrainingAddition": (
        "sagents.v2.optimization",
        "OptimizationTrainingAddition",
    ),
    "OptimizationStabilityCheck": (
        "sagents.v2.optimization",
        "OptimizationStabilityCheck",
    ),
    "OptimizationStoppingPolicy": (
        "sagents.v2.optimization",
        "OptimizationStoppingPolicy",
    ),
    "OptimizationTermination": ("sagents.v2.optimization", "OptimizationTermination"),
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
    "ModelCatalogConfig": ("sagents.v2.model.catalog", "ModelCatalogConfig"),
    "ApplicationConfiguration": (
        "sagents.v2.composition.configuration",
        "ApplicationConfiguration",
    ),
    "SAgentBuilder": ("sagents.v2.builder", "SAgentBuilder"),
    "SAgentRunStream": ("sagents.v2.sagent", "SAgentRunStream"),
    "SessionCommitProposal": ("sagents.v2.contracts", "SessionCommitProposal"),
    "SessionMergeStrategy": ("sagents.v2.contracts", "SessionMergeStrategy"),
    "StartRun": ("sagents.v2.contracts", "StartRun"),
}

__all__ = [
    "RuntimeConfig",
    "SkillModulesConfig",
    "SkillUsageConfig",
    "default_runtime",
    "LoadedAgent",
    "StartupRecoveryIssue",
    "AgentPackageTestGenerator",
    "OptimizationSuiteGeneration",
    "AgentPackageOptimizer",
    "IsolatedOptimizationRunner",
    "OptimizationAgent",
    "OptimizationConstraints",
    "OptimizationCase",
    "OptimizationCaseTrial",
    "OptimizationSuiteIssue",
    "OptimizationSuiteReview",
    "OptimizationSuiteReviewRejected",
    "OptimizationSuite",
    "OptimizationFinalSuite",
    "OptimizationFinalVerification",
    "OptimizationProposalReview",
    "OptimizationFinalSuiteGeneration",
    "OptimizationIteration",
    "OptimizationResult",
    "OptimizationReport",
    "SelfConfigurationService",
    "SelfConfigurationRequest",
    "SqliteSelfConfigurationStore",
    "AgentManagementService",
    "AgentPackageBundle",
    "AgentPackageStore",
    "ActorRef",
    "EventCursor",
    "ExecutionBindingProvider",
    "ExecutionBindingRequest",
    "InterfaceRunStream",
    "ProposeSessionCommit",
    "PublishSessionCommit",
    "RejectSessionCommit",
    "RequestContext",
    "ResolvedApplicationPlan",
    "ResolvedProviderBinding",
    "RunExecutionBinding",
    "RunHandle",
    "RuntimeEvent",
    "SAgent",
    "SAgentApplication",
    "ModelCatalogConfig",
    "ApplicationConfiguration",
    "SAgentBuilder",
    "SAgentRunStream",
    "SessionCommitProposal",
    "SessionMergeStrategy",
    "StartRun",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
