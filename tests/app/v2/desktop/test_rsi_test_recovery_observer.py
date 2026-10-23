import json
import copy

import pytest
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationTestSuite
from tests.sagents.v2.test_package_optimizer import bundle

from app.v2.desktop.backend import rsi_test_recovery as module

factory = module.resumable_human_test_observer


def suite():
    return OptimizationTestSuite(
        cases=tuple(
            OptimizationCase(
                id=x, input="HIDDEN QUESTION " + x, rubric="HIDDEN RUBRIC", split="test"
            )
            for x in ("a", "b")
        )
    )


def record(repeats=1):
    return {
        "round": 0,
        "package_hash": bundle().content_hash,
        "status": "cancelled",
        "valid": True,
        "repeats": repeats,
        "scores": {"test": None},
        "cases": [
            {
                "id": case.id,
                "status": "cancelled",
                "score": None,
                "trials": [
                    {"trial": trial, "status": "cancelled", "score": None}
                    for trial in range(1, repeats + 1)
                ],
            }
            for case in suite().cases
        ],
    }


def complete(row, trial=1, score=0):
    row["trials"][trial - 1].update(
        status="completed",
        score=score,
        passed=score == 1,
        grade={
            "score": score,
            "passed": score == 1,
            "rationale": "HIDDEN FIXED FEEDBACK",
        },
        conversation=[{"role": "assistant", "content": "HIDDEN EXECUTION"}],
    )


def enqueue(observer):
    observer.observe(
        {
            "event": "evaluation_completed",
            "data": {"round": 0, "evaluation": {"cases": []}},
        }
    )


@pytest.mark.asyncio
async def test_resume_keeps_completed_failure_and_executes_only_missing_case():
    old = record()
    complete(old["cases"][0], score=0)
    before = copy.deepcopy(old)
    called = []

    async def evaluate(package, case):
        called.append(case.id)
        return {"grade": {"score": 1, "passed": True, "rationale": "fresh"}}

    published = []
    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=evaluate,
        publish=published.append,
        completed_records=[old],
        concurrency=2,
    )
    enqueue(observer)
    await observer.finish()
    assert called == ["b"]
    assert observer.records[0]["status"] == "completed"
    assert observer.records[0]["scores"]["test"] == 0.5
    assert (
        observer.records[0]["cases"][0]["trials"][0]["grade"]["rationale"]
        == "HIDDEN FIXED FEEDBACK"
    )
    assert old == before
    assert observer.evidence[0]["recovered_measurement"] is True


@pytest.mark.asyncio
async def test_repeated_trials_resume_exact_slots_including_zero_grade():
    old = record(2)
    complete(old["cases"][0], trial=1, score=0)
    complete(old["cases"][1], trial=1, score=1)
    complete(old["cases"][1], trial=2, score=0)
    called = []

    async def evaluate(package, case):
        called.append(case.id)
        return {"grade": {"score": 1, "passed": True, "rationale": "fresh"}}

    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=evaluate,
        publish=lambda _: None,
        completed_records=[old],
        repeats=2,
        concurrency=2,
    )
    enqueue(observer)
    await observer.finish()
    assert called == ["a"]
    assert [
        [t["score"] for t in c["trials"]] for c in observer.records[0]["cases"]
    ] == [[0, 1], [1, 0]]
    assert observer.records[0]["scores"]["test"] == 0.5


@pytest.mark.asyncio
async def test_same_package_next_round_gets_fresh_measurement_not_old_round_cache():
    old = record()
    complete(old["cases"][0], score=0)
    complete(old["cases"][1], score=1)
    called = []

    async def evaluate(package, case):
        called.append(case.id)
        return {"grade": {"score": 1, "passed": True, "rationale": "fresh"}}

    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=evaluate,
        publish=lambda _: None,
        completed_records=[old],
        concurrency=2,
    )
    enqueue(observer)
    observer.observe(
        {
            "event": "round_completed",
            "data": {"record": {"round": 1, "accepted": False}},
        }
    )
    await observer.finish()
    assert sorted(called) == ["a", "b"]
    assert [r["scores"]["test"] for r in observer.records] == [0.5, 1]


@pytest.mark.asyncio
async def test_wrong_package_refuses_cache_instead_of_claiming_grade():
    old = record()
    old["package_hash"] = "wrong"

    async def never(*args):
        pytest.fail("wrong package must not be measured or reused")

    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=never,
        publish=lambda _: None,
        completed_records=[old],
    )
    enqueue(observer)
    await observer.finish()
    assert observer.records[0]["status"] == "error"
    assert observer.records[0]["scores"]["test"] is None
    assert all(
        t["score"] is None for c in observer.records[0]["cases"] for t in c["trials"]
    )


@pytest.mark.parametrize("mutation", ["suite", "repeats", "grade", "duplicate"])
def test_malformed_partial_receipts_are_rejected(mutation):
    old = record()
    complete(old["cases"][0], score=0)
    if mutation == "suite":
        old["cases"][0]["id"] = "unknown"
    if mutation == "repeats":
        old["repeats"] = 2
    if mutation == "grade":
        old["cases"][0]["trials"][0]["score"] = 1
    records = [old, old] if mutation == "duplicate" else [old]
    with pytest.raises(ValueError):
        factory(
            baseline=bundle(),
            suite=suite(),
            evaluate=None,
            publish=lambda _: None,
            completed_records=records,
        )


@pytest.mark.asyncio
async def test_existing_terminal_error_is_preserved_not_resampled():
    old = record()
    old["status"] = "error"

    async def never(*args):
        pytest.fail("terminal error must remain unchanged")

    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=never,
        publish=lambda _: None,
        completed_records=[old],
    )
    enqueue(observer)
    await observer.finish()
    assert observer.records == [old]


@pytest.mark.asyncio
async def test_overlap_invalidates_resumed_checkpoint_without_measuring():
    old = record()

    async def never(*args):
        pytest.fail("overlap must not be measured")

    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=never,
        publish=lambda _: None,
        completed_records=[old],
    )
    observer.observe(
        {
            "event": "suite_fixed",
            "data": {
                "suite": {"cases": [{"id": "train", "input": "HIDDEN QUESTION a"}]}
            },
        }
    )
    enqueue(observer)
    await observer.finish()
    assert observer.records[0]["status"] == "invalid"
    assert observer.records[0]["valid"] is False


@pytest.mark.asyncio
async def test_postrun_human_replay_never_calls_optimizer_and_preserves_selection():
    from tests.sagents.v2.test_package_optimizer import (
        AdaptiveRunner,
        context,
        optimizer,
    )

    runner = AdaptiveRunner(
        scores={
            "base": {"training": 0.4, "validation": 0.4},
            "guidance-1": {"training": 0.3, "validation": 0.8},
            "guidance-2": {"training": 0.6, "validation": 0.8},
        }
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Conversions",
        rounds=2,
        validation_case_count=2,
    )
    original = result.model_dump_json()
    requests = copy.deepcopy(runner.requests)
    events = module.completed_checkpoint_events(bundle(), result)
    assert [
        e["data"].get("round", e["data"].get("record", {}).get("round"))
        for e in events[1:]
    ] == [0, 1, 2]
    for score in (0, 1):

        async def evaluate(package, case):
            return {
                "grade": {
                    "score": score,
                    "passed": score == 1,
                    "rationale": "HIDDEN HUMAN FEEDBACK",
                }
            }

        observer = factory(
            baseline=bundle(),
            suite=suite(),
            evaluate=evaluate,
            publish=lambda _: None,
            concurrency=2,
        )
        for event in events:
            observer.observe(event)
        await observer.finish()
        assert [r["scores"]["test"] for r in observer.records] == [score] * 3
        assert result.model_dump_json() == original
        assert runner.requests == requests
        assert "HIDDEN HUMAN FEEDBACK" not in json.dumps(runner.requests)


@pytest.mark.asyncio
async def test_postrun_replay_reuses_partial_baseline_and_measures_predeclared_later_rounds():
    from tests.sagents.v2.test_package_optimizer import (
        AdaptiveRunner,
        context,
        optimizer,
    )

    runner = AdaptiveRunner(
        scores={
            "base": {"training": 0.4, "validation": 0.4},
            "guidance-1": {"training": 0.5, "validation": 0.8},
        }
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Conversions",
        rounds=1,
        validation_case_count=2,
    )
    old = record()
    complete(old["cases"][0], score=0)
    events = module.completed_checkpoint_events(bundle(), result, saved_records=[old])
    calls = []

    async def evaluate(package, case):
        calls.append((package.content_hash, case.id))
        return {"grade": {"score": 1, "passed": True, "rationale": "fresh"}}

    observer = factory(
        baseline=bundle(),
        suite=suite(),
        evaluate=evaluate,
        publish=lambda _: None,
        completed_records=[old],
        concurrency=2,
    )
    for e in events:
        observer.observe(e)
    await observer.finish()
    assert len(calls) == 3
    assert (bundle().content_hash, "a") not in calls
    assert [r["scores"]["test"] for r in observer.records] == [0.5, 1]


@pytest.mark.asyncio
async def test_postrun_checkpoint_identity_mismatch_is_rejected_before_execution():
    from tests.sagents.v2.test_package_optimizer import (
        AdaptiveRunner,
        context,
        optimizer,
    )

    runner = AdaptiveRunner(
        scores={
            "base": {"training": 0.4, "validation": 0.4},
            "guidance-1": {"training": 0.5, "validation": 0.8},
        }
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Conversions",
        rounds=1,
        validation_case_count=2,
    )
    with pytest.raises(ValueError, match="baseline differs"):
        module.completed_checkpoint_events(bundle("wrong"), result)
    bad = record()
    bad["package_hash"] = "wrong"
    with pytest.raises(ValueError, match="saved human checkpoint differs"):
        module.completed_checkpoint_events(bundle(), result, saved_records=[bad])
    bad = record()
    bad["round"] = 999
    with pytest.raises(ValueError, match="saved human checkpoint differs"):
        module.completed_checkpoint_events(bundle(), result, saved_records=[bad])
    altered = result.model_copy(update={"candidate_package": bundle("wrong")})
    with pytest.raises(ValueError, match="retained package differs"):
        module.completed_checkpoint_events(bundle(), altered)
