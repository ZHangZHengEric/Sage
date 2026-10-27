"""Overall adaptive quality permits local tradeoffs and tracks their repair."""

import json

import pytest

from sagents.v2 import AgentPackageOptimizer
from sagents.v2.optimization.contracts import (
    OptimizationCase, OptimizationCaseResult, OptimizationEvaluation,
    OptimizationGrade, OptimizationObservation,
)
from tests.sagents.v2.test_package_optimizer import AdaptiveRunner, bundle, context, optimizer


def evaluation(training, validation, *, training_passed=None):
    cases = []
    for split, scores in (("training", training), ("validation", validation)):
        for i, score in enumerate(scores):
            passed = training_passed[i] if split == "training" and training_passed is not None else score == 1
            cases.append(OptimizationCaseResult(case=OptimizationCase(id=f"{split}-{i}",
                split=split, input=f"{split} question {i}", rubric="Correct"),
                observation=OptimizationObservation(state="completed"),
                grade=OptimizationGrade(score=score, passed=passed, rationale="Observed")))
    return OptimizationEvaluation(package_hash="package", cases=tuple(cases))


def test_tau_tradeoff_is_accepted_and_regression_is_recorded():
    old = evaluation([1] * 6, [0, 1, 1, 0])
    new = evaluation([1] * 5 + [0], [1] * 4)
    accepted, reason = AgentPackageOptimizer._select_adaptive(old, new, 0.01)
    assert accepted and "1 case regressions" in reason
    assert old.overall_score() == 0.75
    assert new.overall_score() == pytest.approx(11 / 12)
    regression, = AgentPackageOptimizer._regressions(old, new)
    assert regression.case_id == "training-5"
    assert regression.previous_score == 1 and regression.current_score == 0


def test_training_growth_does_not_change_split_weights_or_hide_overall_loss():
    old = evaluation([0.8] * 100, [0.8])
    new = evaluation([0.9] * 100, [0.6])
    assert not AgentPackageOptimizer._select_adaptive(old, new, 0.01)[0]
    assert not AgentPackageOptimizer._select_adaptive(old, old, 0.01)[0]
    small = evaluation([0.81] * 100, [0.8])
    assert not AgentPackageOptimizer._select_adaptive(old, small, 0.01)[0]


def test_alignment_execution_and_generated_tool_integrity_still_gate_selection():
    old = evaluation([0], [0])
    new = evaluation([1], [1])
    for observation in (
        OptimizationObservation(state="failed"),
        OptimizationObservation(state="completed", evidence={"generated_tool_audit": {"passed": False}}),
    ):
        broken = new.model_copy(update={"cases": (new.cases[0].model_copy(update={"observation": observation}), new.cases[1])})
        assert not AgentPackageOptimizer._select_adaptive(old, broken, 0.01)[0]
    # Shared cases are aligned by identity: arrival order may change when the
    # training set grows, while missing or changed cases remain invalid.
    reordered = new.model_copy(update={"cases": tuple(reversed(new.cases))})
    assert AgentPackageOptimizer._select_adaptive(old, reordered, 0.01)[0]
    assert not AgentPackageOptimizer._regressions(old, reordered)
    with pytest.raises(ValueError, match="missing or changed"):
        AgentPackageOptimizer._select_adaptive(
            old, new.model_copy(update={"cases": new.cases[:-1]}), 0.01)
    changed = new.cases[0].model_copy(update={
        "case": new.cases[0].case.model_copy(update={"input": "different task"})})
    with pytest.raises(ValueError, match="missing or changed"):
        AgentPackageOptimizer._select_adaptive(
            old, new.model_copy(update={"cases": (changed, new.cases[1])}), 0.01)


def test_regression_debt_survives_other_improvements_until_repaired():
    old = evaluation([1, 0.4], [0.4])
    first = evaluation([0.5, 0.8], [0.8])
    debt = AgentPackageOptimizer._regressions(old, first)
    second = evaluation([0.7, 1], [1])
    debt = AgentPackageOptimizer._outstanding_regressions(debt, (), second)
    assert len(debt) == 1 and debt[0].previous_score == 1 and debt[0].current_score == 0.7
    assert not AgentPackageOptimizer._outstanding_regressions(debt, (), evaluation([1, 1], [1]))


@pytest.mark.asyncio
async def test_next_round_uses_overall_better_parent_and_training_regressions_only():
    runner = AdaptiveRunner(scores={
        "base": {"training": 0.4, "validation": 0.4},
        "guidance-1": {"training": 0.3, "validation": 0.8},
        "guidance-2": {"training": 0.6, "validation": 0.8},
    })
    result = await optimizer(runner).optimize(bundle(), context=context(), goal="Conversions",
        rounds=2, validation_case_count=2)
    first, second = result.report.rounds
    assert first.accepted and second.accepted
    assert second.parent_hash == first.candidate_package.content_hash
    assert first.overall_before == pytest.approx(0.4)
    assert first.overall_after == pytest.approx(0.55)
    assert first.regressions and all(r.split == "training" for r in first.regressions)
    requests = [json.loads(text)["data"] for name, text in runner.requests if name == "test.tuner"]
    assert requests[1]["selection_policy"]["individual_regressions_allowed"] is True
    assert requests[1]["selected_round"] == 1
    assert requests[1]["previous_attempts"][0]["accepted"] is True
    assert requests[1]["training_regressions"]
    assert all(r["current"]["case"]["split"] == "training" for r in requests[1]["training_regressions"])
    assert "validation secret task" not in json.dumps(requests[1])
    assert "validation" not in requests[1] and "validation_history" not in requests[1]


@pytest.mark.asyncio
async def test_rejected_compliant_attempt_is_not_presented_as_retained_to_tuner():
    runner = AdaptiveRunner(scores={
        "base": {"training": 0.8, "validation": 0.8},
        "guidance-1": {"training": 0.9, "validation": 0.5},
        "guidance-2": {"training": 0.9, "validation": 0.9},
    })
    result = await optimizer(runner).optimize(bundle(), context=context(), goal="Conversions",
        rounds=2, validation_case_count=2)
    first, second = result.report.rounds
    assert first.review.approved and not first.accepted
    assert second.accepted and second.parent_hash == first.parent_hash
    requests = [json.loads(text)["data"] for name, text in runner.requests if name == "test.tuner"]
    next_request = requests[1]
    attempt, = next_request["previous_attempts"]
    assert next_request["selected_round"] == 0
    assert attempt["accepted"] is False
    assert "overall_before" not in attempt and "overall_after" not in attempt
    assert first.overall_before == pytest.approx(0.8)
    assert first.overall_after == pytest.approx(0.7)
    assert attempt["semantic_review"]["approved"] is True
    assert "guidance-1" not in json.dumps(next_request["package"])
    assert "accepted=false are not part of that parent" in next_request["feedback_note"]
    assert "reason" not in attempt  # No free-text rejection that might name a dev case.
    assert "validation secret task" not in json.dumps(next_request)
