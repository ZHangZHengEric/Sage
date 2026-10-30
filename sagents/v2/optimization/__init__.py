"""Independent AgentPackage evaluation and tuning API."""
from sagents.v2.optimization.dataset import OptimizationDataset
from sagents.v2.optimization.dataset_versions import DatasetVersion, DatasetRevisionRequest, CaseExclusionProposal, SuitePreflightPolicy
from sagents.v2.optimization.builtin_scoring import BuiltinScoring
from sagents.v2.optimization.comparison_plugin import (
    ComparisonPreparationRequest, ComparisonRequest, PreparedComparisonArtifact, FrozenComparisonFile, PythonComparisonPlugin, ComparisonPlugin, DiagnosticEvidence, EvaluationPresentation,
)
from sagents.v2.optimization.pairwise import PairwiseDecision, PairwiseEvaluator, PairwiseMeasurementError
from sagents.v2.optimization.scoring import ExecutionScorer, ScorerDescriptor, ScoringRequest, ScoringResult
from sagents.v2.optimization.evaluation_plugin import (
    EvaluationCapabilities, EvaluationRequest, EvaluationResult, AnalysisRequest, SummaryRequest, PythonEvaluationPlugin,
)

from sagents.v2.optimization.contracts import (
    OptimizationTestSuite,
    OptimizationCaseBatch,
    OptimizationCaseBatchGeneration,
    OptimizationTrainingAddition,
    OptimizationAgent,
    OptimizationFinalSuite,
    OptimizationFinalVerification,
    OptimizationProposalReview,
    OptimizationFinalSuiteGeneration,
    OptimizationAgentCall,
    OptimizationCase,
    OptimizationCaseResult,
    OptimizationCaseTrial,
    OptimizationDialogueReply,
    OptimizationDialogueTurn,
    OptimizationConstraints,
    OptimizationEvaluation,
    OptimizationGrade,
    OptimizationDiagnosis,
    OptimizationFinding,
    OptimizationDiagnosisSummary,
    OptimizationPriority,
    OptimizationIteration,
    OptimizationObservation,
    OptimizationPatch,
    OptimizationReport,
    OptimizationStoppingPolicy,
    OptimizationStabilityCheck,
    OptimizationTermination,
    OptimizationResult,
    OptimizationRound,
    OptimizationRegression,
    OptimizationSuite,
    OptimizationSuiteIssue,
    OptimizationSuiteReview,
    OptimizationSuiteGeneration,
)
from sagents.v2.optimization.recovery import OptimizationRecoveryRequired, OptimizationTransientFailure
from sagents.v2.optimization.generator import AgentPackageTestGenerator
from sagents.v2.optimization.optimizer import (
    AgentPackageOptimizer,
    OptimizationSuiteReviewRejected,
)
from sagents.v2.optimization.runner import (
    IsolatedOptimizationRunner,
    OptimizationRunner,
)

from sagents.v2.optimization.observer import HumanTestObserver, IsolatedTestEvaluator
from sagents.v2.optimization.user_simulator import UserSimulator, UserSimulatorDescriptor, UserSimulationRequest, UserSimulationReply
from sagents.v2.optimization.python_user_simulator import PythonUserSimulator
from sagents.v2.optimization.default_user_simulator import DefaultUserSimulator
from sagents.v2.optimization.contracts import OptimizationExperiment

__all__ = [
    "DiagnosticEvidence", "EvaluationPresentation",
    "EvaluationCapabilities", "EvaluationRequest", "EvaluationResult", "AnalysisRequest", "SummaryRequest", "PythonEvaluationPlugin",
    "ComparisonPlugin", "ComparisonPreparationRequest", "ComparisonRequest", "PreparedComparisonArtifact", "FrozenComparisonFile",
    "PythonComparisonPlugin", "PairwiseDecision", "PairwiseEvaluator", "PairwiseMeasurementError",
    "BuiltinScoring", "UserSimulator", "UserSimulatorDescriptor", "UserSimulationRequest", "UserSimulationReply",
    "PythonUserSimulator", "DefaultUserSimulator", "OptimizationExperiment",
    "OptimizationDataset",
    "DatasetVersion",
    "DatasetRevisionRequest",
    "CaseExclusionProposal",
    "SuitePreflightPolicy",
    "ExecutionScorer",
    "ScorerDescriptor",
    "ScoringRequest",
    "ScoringResult",
    "OptimizationRecoveryRequired",
    "OptimizationTransientFailure",
    "OptimizationTestSuite",
    "HumanTestObserver",
    "IsolatedTestEvaluator",
    "AgentPackageOptimizer",
    "AgentPackageTestGenerator",
    "OptimizationSuiteGeneration",
    "IsolatedOptimizationRunner",
    "OptimizationRunner",
    "OptimizationCaseBatch",
    "OptimizationCaseBatchGeneration",
    "OptimizationTrainingAddition",
    "OptimizationAgent",
    "OptimizationFinalSuite",
    "OptimizationFinalVerification",
    "OptimizationProposalReview",
    "OptimizationFinalSuiteGeneration",
    "OptimizationAgentCall",
    "OptimizationCase",
    "OptimizationCaseResult",
    "OptimizationCaseTrial",
    "OptimizationDialogueReply",
    "OptimizationDialogueTurn",
    "OptimizationConstraints",
    "OptimizationEvaluation",
    "OptimizationGrade",
    "OptimizationDiagnosis",
    "OptimizationFinding",
    "OptimizationDiagnosisSummary",
    "OptimizationPriority",
    "OptimizationIteration",
    "OptimizationObservation",
    "OptimizationPatch",
    "OptimizationReport",
    "OptimizationStoppingPolicy",
    "OptimizationStabilityCheck",
    "OptimizationTermination",
    "OptimizationResult",
    "OptimizationRound",
    "OptimizationRegression",
    "OptimizationSuite",
    "OptimizationSuiteIssue",
    "OptimizationSuiteReview",
    "OptimizationSuiteReviewRejected",
]
