"""Public, serializable contracts for bounded package optimization."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.tool.generated import GeneratedTool
from sagents.v2.contracts.common import StrictModel, VerbatimText, ToolName, SkillName

OptimizationPart = Literal["instructions", "skills", "tools", "budgets", "resources"]


class OptimizationCase(StrictModel):
    id: str
    input: VerbatimText = Field(min_length=1)
    rubric: VerbatimText = Field(min_length=1)
    split: Literal["training", "validation", "test", "final"] = "training"
    mode: Literal["single_turn", "dialogue"] = "single_turn"
    max_turns: int = Field(default=5, ge=1, le=20)
    user_context: VerbatimText = ""
    coverage_tags: tuple[str, ...] = ()


class OptimizationSuite(StrictModel):
    cases: tuple[OptimizationCase, ...]

    @model_validator(mode="after")
    def check_cases(self):
        if not 2 <= len(self.cases) <= 10000:
            raise ValueError("suite requires 2 to 10000 cases")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case ids must be unique")
        if {case.split for case in self.cases} != {"training", "validation"}:
            raise ValueError("suite requires training and validation cases")
        return self


class OptimizationTestSuite(StrictModel):
    """Human-only observation tasks; never an optimizer input."""

    cases: tuple[OptimizationCase, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("test case ids must be unique")
        if any(case.split != "test" for case in self.cases):
            raise ValueError("test suite cases must use split=test")
        return self


class OptimizationFinalSuite(StrictModel):
    cases: tuple[OptimizationCase, ...]

    @model_validator(mode="after")
    def check_cases(self):
        if not 1 <= len(self.cases) <= 100:
            raise ValueError("final suite requires 1 to 100 cases")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("final case ids must be unique")
        if any(case.split != "final" for case in self.cases):
            raise ValueError("final suite cases must use split=final")
        return self

    def assert_disjoint(self, cases):
        known_ids = {case.id for case in cases}
        known_inputs = {" ".join(case.input.split()) for case in cases}
        for case in self.cases:
            if case.id in known_ids or " ".join(case.input.split()) in known_inputs:
                raise ValueError("final cases must be distinct from optimization cases")


class OptimizationConstraints(StrictModel):
    # Original instructions are preserved; only a separate guidance overlay changes.
    allow_instruction_guidance: bool = True
    editable_files: tuple[str, ...] = ()
    creatable_files: tuple[str, ...] = ()
    allow_tool_changes: bool = False
    allow_tool_creation: bool = False
    require_clean_generated_tools: bool = False
    allow_skill_changes: bool = False
    tool_candidates: dict[ToolName, str] = Field(default_factory=dict)
    skill_candidates: dict[SkillName, str] = Field(default_factory=dict)
    max_guidance_chars: int = Field(default=16000, ge=1, le=1000000)
    max_file_bytes: int = Field(default=262144, ge=1, le=10000000)
    editable_budget_fields: tuple[
        Literal[
            "max_steps",
            "input_tokens",
            "system_tokens",
            "protected_recent_tokens",
            "output_tokens",
            "total_tokens",
            "wall_time_seconds",
        ],
        ...,
    ] = ()


class OptimizationPatch(StrictModel):
    rationale: str = Field(min_length=1)
    tool_definitions: dict[ToolName, GeneratedTool] = Field(default_factory=dict)
    instruction_guidance: VerbatimText | None = None
    files: dict[str, VerbatimText] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)
    tools: tuple[ToolName, ...] | None = None
    skills: tuple[SkillName, ...] | None = None


class OptimizationObservation(StrictModel):
    state: Literal["completed", "failed", "cancelled", "suspended"]
    output: VerbatimText = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class OptimizationGrade(StrictModel):
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    passed: bool
    rationale: str = Field(min_length=1)


class OptimizationDialogueReply(StrictModel):
    can_continue: bool
    message: VerbatimText = ""
    rationale: str


class OptimizationDialogueTurn(StrictModel):
    turn: int
    input: VerbatimText
    observation: OptimizationObservation
    grade: OptimizationGrade
    model_grade: OptimizationGrade | None = None


class OptimizationCaseTrial(StrictModel):
    observation: OptimizationObservation
    grade: OptimizationGrade
    model_grade: OptimizationGrade | None = None
    dialogue: tuple[OptimizationDialogueTurn, ...] = ()
    stop_reason: str | None = None


class OptimizationCaseResult(OptimizationCaseTrial):
    case: OptimizationCase
    trials: tuple[OptimizationCaseTrial, ...] = ()


class OptimizationEvaluation(StrictModel):
    package_hash: str
    cases: tuple[OptimizationCaseResult, ...]

    def mean_score(self, split: str) -> float:
        grades = [item.grade.score for item in self.cases if item.case.split == split]
        return sum(grades) / len(grades)

    def overall_score(self) -> float:
        """Equal split weights remain stable as training questions accumulate."""
        return (self.mean_score("training") + self.mean_score("validation")) / 2


class OptimizationSuiteIssue(StrictModel):
    kind: Literal[
        "goal_conflict",
        "ambiguous_rubric",
        "untestable",
        "split_leakage",
        "coverage_gap",
    ]
    severity: Literal["blocking", "advisory"]
    case_ids: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)
    suggested_fix: str = Field(min_length=1)


class OptimizationSuiteReview(StrictModel):
    approved: bool
    rationale: str = Field(min_length=1)
    issues: tuple[OptimizationSuiteIssue, ...] = ()

    @model_validator(mode="after")
    def check_decision(self):
        blocked = any(issue.severity == "blocking" for issue in self.issues)
        if self.approved == blocked:
            raise ValueError("suite approval must agree with blocking issues")
        return self


class OptimizationProposalReview(StrictModel):
    approved: bool
    memorization_detected: bool = False
    goal_drift_detected: bool
    permission_drift_detected: bool
    rationale: str = Field(min_length=1)
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_approval(self):
        if self.approved and (
            self.goal_drift_detected or self.permission_drift_detected
        ):
            raise ValueError("review cannot approve a detected semantic violation")
        return self


class OptimizationRegression(StrictModel):
    case_id: str
    split: Literal["training", "validation", "final"]
    previous_score: float
    current_score: float
    previous_passed: bool
    current_passed: bool


class OptimizationRound(StrictModel):
    round: int
    parent_hash: str
    candidate_package: AgentPackageBundle | None = None
    patch: OptimizationPatch | None = None
    evaluation: OptimizationEvaluation | None = None
    accepted: bool
    reason: str
    evaluation_reused: bool = False
    review: OptimizationProposalReview | None = None
    overall_before: float | None = None
    overall_after: float | None = None
    regressions: tuple[OptimizationRegression, ...] = ()


class OptimizationAgent(StrictModel):
    package: AgentPackageBundle
    agent_id: str

    @model_validator(mode="after")
    def agent_exists(self):
        if self.agent_id not in self.package.manifest.agents:
            raise ValueError("internal agent does not exist in package")
        self.package.resolved_manifest()
        return self


class OptimizationAgentCall(StrictModel):
    role: Literal[
        "test_design",
        "test_dialogue",
        "evaluation",
        "tuning",
        "semantic_review",
        "suite_review",
    ]
    observation: OptimizationObservation
    request: VerbatimText = ""
    round: int = 0
    case_id: str | None = None
    trial: int = Field(default=1, ge=1)
    phase: Literal["optimization", "training_challenge", "final"] = "optimization"


class OptimizationFinalVerification(StrictModel):
    suite: OptimizationFinalSuite
    baseline: OptimizationEvaluation
    candidate: OptimizationEvaluation
    candidate_iteration: int
    passed: bool
    reason: str
    evaluation_reused: bool = False


class OptimizationStoppingPolicy(StrictModel):
    target_score: float = Field(default=0.95, gt=0, le=1, allow_inf_nan=False)
    patience: int = Field(default=3, ge=1, le=100)
    stability_passes: int = Field(default=2, ge=2, le=5)


class OptimizationTermination(StrictModel):
    reason: Literal["target_reached", "stagnation", "round_limit"]
    completed_rounds: int
    stability_passes: int = 0
    final_passed: bool | None = None


class OptimizationStabilityCheck(StrictModel):
    round: int
    attempt: int
    confirmation: int
    passed: bool
    evaluation: OptimizationEvaluation


class OptimizationTrainingAddition(StrictModel):
    round: int
    cases: tuple[OptimizationCase, ...]


class OptimizationReport(StrictModel):
    goal: VerbatimText
    suite_review: OptimizationSuiteReview | None = None
    requested_rounds: int
    suite: OptimizationSuite
    baseline: OptimizationEvaluation
    selected: OptimizationEvaluation
    rounds: tuple[OptimizationRound, ...]
    agent_calls: tuple[OptimizationAgentCall, ...]
    improved: bool
    generated_tool_audit_required: bool = False
    goal_verified: bool | None = None
    recommendation_block_reason: str | None = None
    stability_checks: tuple[OptimizationStabilityCheck, ...] = ()
    training_additions: tuple[OptimizationTrainingAddition, ...] = ()
    stopping_policy: OptimizationStoppingPolicy | None = None
    termination: OptimizationTermination | None = None
    internal_agents: dict[str, OptimizationAgent] = Field(default_factory=dict)
    evaluation_repeats: int = 1
    final_verification: OptimizationFinalVerification | None = None
    optimization_scope: tuple[OptimizationPart, ...] | None = None


class OptimizationIteration(StrictModel):
    iteration: int
    package: AgentPackageBundle
    evaluation: OptimizationEvaluation | None = None
    patch: OptimizationPatch | None = None
    recommended: bool = False
    evaluation_reused: bool = False
    reason: str
    review: OptimizationProposalReview | None = None


class OptimizationResult(StrictModel):
    candidate_package: AgentPackageBundle
    report: OptimizationReport
    iterations: tuple[OptimizationIteration, ...] = ()


class OptimizationSuiteGeneration(StrictModel):
    suite: OptimizationSuite
    designer: OptimizationAgent
    call: OptimizationAgentCall


class OptimizationFinalSuiteGeneration(StrictModel):
    suite: OptimizationFinalSuite
    designer: OptimizationAgent
    call: OptimizationAgentCall


class OptimizationCaseBatch(StrictModel):
    """One independently designed split; training accumulates across batches."""

    cases: tuple[OptimizationCase, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case ids must be unique")
        if len({case.split for case in self.cases}) != 1:
            raise ValueError("a batch must contain one split")
        return self


class OptimizationCaseBatchGeneration(StrictModel):
    suite: OptimizationCaseBatch
    designer: OptimizationAgent
    call: OptimizationAgentCall
