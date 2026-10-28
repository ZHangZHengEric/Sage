import json
import pytest
from sagents.v2.optimization.contracts import OptimizationGrade
from sagents.v2.optimization.diagnostics import diagnose_scored_execution
from sagents.v2.optimization.principles import EVALUATION_PRINCIPLES
from sagents.v2.optimization.runner import OPTIMIZATION_TRIAL
from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner, diagnosis
from tests.sagents.v2.test_package_optimizer import bundle, context, optimizer, suite


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_fixed_grade_diagnosis_distinguishes_original_contract_without_duplicate_baseline(
    changed,
):
    requests = []

    async def invoke(request):
        requests.append(request)
        return json.dumps(diagnosis())

    original = "Help with conversion. Never send messages."
    policy = original + " Refuse all clarifications." if changed else original
    result = await diagnose_scored_execution(
        grade=OptimizationGrade(score=0, passed=False, rationale="Fixed checker"),
        entries=[{"user": "Question"}],
        rubric="Solve",
        policy=policy,
        original_policy=original,
        case_context={"user_context": "Evaluator-only scenario, not user consent"},
        file_backed=True,
        invoke=invoke,
    )
    data = requests[0]["data"]
    assert data["original_policy"] == (original if changed else None)
    assert data["policy"] == policy and "Evaluator-only" in data["case"]["user_context"]
    assert result.score == 0 and not result.passed
    assert "distinguish original_policy from candidate policy" in requests[0]["task"]
    principles = " ".join(EVALUATION_PRINCIPLES.split())
    assert "cannot redefine success or become immutable authority" in principles
    assert "not target knowledge or user consent" in principles
    assert "lawful workflow hypothesis, not a proven fix" in principles


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_real_optimizer_binds_original_contract_and_scenario_to_eval_only(
    external,
):
    class Capture(DiagnosticRunner):
        evaluation_requests = []

        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.evaluator":
                self.evaluation_requests.append(json.loads(content))
            return await super().run(package, agent_id, content, ctx)

    runner = Capture()
    runner.proposals = [
        {"rationale": "Consolidate procedure", "instruction_guidance": "guidance-1"},
        {"rationale": "Refine procedure", "instruction_guidance": "guidance-2"},
    ]
    s = suite()
    s = s.model_copy(
        update={
            "cases": tuple(
                c.model_copy(
                    update={
                        "user_context": "PRIVATE DEV SCENARIO"
                        if c.split == "validation"
                        else "Public training scenario"
                    }
                )
                for c in s.cases
            )
        }
    )

    async def score(case, observation):
        value = (0.4 if OPTIMIZATION_TRIAL.get() == 1 else 0.8) + (
            0.1 if observation.output != "base" else 0
        )
        return OptimizationGrade(score=value, passed=value > 0.5, rationale="Fixed")

    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Conversions",
        suite=s,
        validation_case_count=1,
        grow_training=False,
        rounds=2,
        evaluation_repeats=2,
        evaluation_aggregation="mean",
        **({"authoritative_grader": score} if external else {}),
    )
    original = bundle().resolved_manifest().agents["assistant"].instructions.inline
    requests = [
        r
        for r in runner.evaluation_requests
        if r["response_schema"]["title"]
        in ("OptimizationGrade", "OptimizationDiagnosis")
    ]
    changed = [r for r in requests if r["data"]["policy"] != original]
    assert changed
    summaries = [
        r
        for r in runner.evaluation_requests
        if r["response_schema"]["title"] == "OptimizationDiagnosisSummary"
    ]
    assert len(summaries) == 2
    assert summaries[0]["data"]["original_policy"] is None
    assert summaries[1]["data"]["policy"] != original
    assert summaries[1]["data"]["original_policy"] == original
    assert all(r["data"]["original_policy"] == original for r in changed)
    if external:
        assert all("user_context" in r["data"]["case"] for r in changed)
        assert any(r["task"].startswith("Compare repeated") for r in changed)
    tuning = [
        json.loads(text)["data"]
        for name, text in runner.requests
        if name == "test.tuner"
    ]
    assert "PRIVATE DEV SCENARIO" not in json.dumps(tuning)
    assert result.report.baseline.cases[0].grade.score == pytest.approx(
        0.6 if external else 0.4
    )
