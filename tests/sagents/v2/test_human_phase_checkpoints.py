import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationObservation
from sagents.v2.optimization.observer import (
    IsolatedTestEvaluator,
    _MEASUREMENT_IDENTITY,
)
from tests.sagents.v2.test_call_isolation import isolated_optimizer
from tests.sagents.v2.test_package_optimizer import bundle, context, suite
from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["scoring", "evaluation"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_resume_completed_execution_or_zero_score_without_resampling(
    tmp_path, phase, cancel
):
    counts = {"target": 0, "score": 0, "diagnosis": 0}
    broken = True

    class Target(Runner):
        @asynccontextmanager
        async def conversation(self, *args):
            async def send(content):
                counts["target"] += 1
                return OptimizationObservation(
                    state="completed", output="Visible response"
                )

            yield SimpleNamespace(send=send)

    runner = Target()
    roles = isolated_optimizer(runner)

    class Evaluate(IsolatedTestEvaluator):
        async def _grade_execution(self, *args):
            counts["score"] += 1
            if broken and phase == "scoring":
                raise (
                    asyncio.CancelledError()
                    if cancel
                    else RuntimeError("scorer disconnected")
                )
            return OptimizationGrade(
                score=0, passed=False, rationale="Authoritative zero"
            )

        async def _ask(self, agent, task, data, schema):
            if schema.__name__ == "OptimizationDiagnosis":
                counts["diagnosis"] += 1
                if broken and phase == "evaluation":
                    raise (
                        asyncio.CancelledError()
                        if cancel
                        else RuntimeError("diagnosis disconnected")
                    )
            return await super()._ask(agent, task, data, schema)

    def make():
        return Evaluate(
            runner=runner,
            evaluator=roles.evaluator,
            driver=roles.test_driver,
            context=context(),
            goal="Accuracy",
            scorer=object(),
            call_retries=1,
            max_transport_retries=0,
            evidence_directory=tmp_path,
            checkpoint_binding_id="frozen-host-config/v1",
        )

    token = _MEASUREMENT_IDENTITY.set((3, 1))
    try:
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await make()(bundle(), suite().cases[0])
        receipts = list((tmp_path / ".phase-checkpoints").glob("*.json"))
        assert len(receipts) == 1
        saved = json.loads(receipts[0].read_text())["payload"]
        assert (saved["grade"] is None) == (phase == "scoring")
        broken = False
        result = await make()(bundle(), suite().cases[0])
        assert result["grade"]["score"] == 0
        assert counts["target"] == 1
        assert counts["score"] == (2 if phase == "scoring" else 1)
        assert counts["diagnosis"] == (2 if phase == "evaluation" else 1)
        # Corruption fails closed before execution or scoring.
        receipt = json.loads(receipts[0].read_text())
        receipt["payload"]["grade"]["score"] = 1
        receipts[0].write_text(json.dumps(receipt))
        before = counts.copy()
        with pytest.raises(ValueError, match="checkpoint differs"):
            await make()(bundle(), suite().cases[0])
        assert counts == before
    finally:
        _MEASUREMENT_IDENTITY.reset(token)


@pytest.mark.asyncio
async def test_old_diagnosis_error_recovers_only_diagnosis_and_preserves_zero():
    from app.v2.desktop.backend.rsi_test_recovery import resumable_human_test_observer
    from tests.app.v2.desktop.test_rsi_test_recovery_observer import (
        record,
        complete,
        suite as hidden_suite,
        enqueue,
    )

    old = record()
    complete(old["cases"][0], score=0)
    old["cases"][0]["trials"][0]["status"] = "error"
    old["cases"][0]["trials"][0]["diagnosis_status"] = "error"
    complete(old["cases"][1], score=1)
    old["status"] = "error"
    calls = []

    class Evaluate:
        async def __call__(self, package, case):
            raise AssertionError("Already scored targets must never execute again")

        async def resume_measurement(self, package, case, saved):
            calls.append(case.id)
            assert saved["grade"]["score"] == 0
            return saved

    observer = resumable_human_test_observer(
        baseline=bundle(),
        suite=hidden_suite(),
        evaluate=Evaluate(),
        publish=lambda value: None,
        completed_records=[old],
    )
    enqueue(observer)
    await observer.finish()
    assert calls == ["a"]
    assert observer.records[0]["status"] == "completed"
    assert observer.records[0]["scores"]["test"] == 0.5
