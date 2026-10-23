import copy
import json
from app.v2.desktop.backend import rsi_test_recovery as recovery_helper
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from sagents.v2.optimization import OptimizationAgent
from sagents.v2.optimization.contracts import (
    OptimizationDialogueReply,
    OptimizationObservation,
)
from sagents.v2.optimization.observer import IsolatedTestEvaluator
from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner, Scorer
from tests.sagents.v2.test_package_optimizer import bundle, context, suite
from tests.app.v2.desktop.test_rsi_test_recovery_observer import (
    record,
    complete,
    enqueue,
)


class InvalidUserRunner(Runner):
    def __init__(self, fail_always=False):
        super().__init__()
        self.fail_always = fail_always
        self.user_requests = []
        self.target_sends = 0

    @asynccontextmanager
    async def conversation(self, *args):
        async with super().conversation(*args) as session:

            async def send(content):
                self.target_sends += 1
                return await session.send(content)

            yield SimpleNamespace(send=send)

    async def run(self, package, agent_id, content, ctx):
        request = json.loads(content)
        if (
            request.get("response_schema", {}).get("title")
            == "OptimizationDialogueReply"
        ):
            self.user_requests.append(request)
            if self.fail_always or len(self.user_requests) == 1:
                kind = getattr(self, "invalid_kind", "bool")
                invalid = {
                    "bool": json.dumps(
                        {
                            "can_continue": "not-a-boolean",
                            "message": "Keep original goal",
                            "rationale": "Known user context only",
                        }
                    ),
                    "syntax": "{not valid JSON}",
                    "missing_field": json.dumps(
                        {"can_continue": True, "message": "Continue"}
                    ),
                    "empty_message": json.dumps(
                        {
                            "can_continue": True,
                            "message": "   ",
                            "rationale": "Continue original goal",
                        }
                    ),
                }[kind]
                return OptimizationObservation(state="completed", output=invalid)
        return await super().run(package, agent_id, content, ctx)


def measure(runner, scorer=None):
    agent = OptimizationAgent(package=bundle("evaluator"), agent_id="assistant")
    driver_package = bundle("designer")
    driver_package.manifest.agents["assistant"] = driver_package.manifest.agents[
        "assistant"
    ].model_copy(update={"tools": ()})
    driver = OptimizationAgent(package=driver_package, agent_id="assistant")
    return IsolatedTestEvaluator(
        runner=runner,
        evaluator=agent,
        driver=driver,
        context=context(),
        goal="Accuracy",
        scorer=scorer,
    )


def patch(monkeypatch):
    import sys

    staged = vars(recovery_helper)
    monkeypatch.setattr(
        sys.modules[__name__],
        "IsolatedTestEvaluator",
        staged["RecoveringIsolatedTestEvaluator"],
    )


@pytest.mark.asyncio
async def test_original_invalid_user_json_aborts_after_first_reply():
    runner = InvalidUserRunner()
    scorer = Scorer()
    evaluator = measure(runner, scorer)
    case = (
        suite()
        .cases[0]
        .model_copy(
            update={"mode": "dialogue", "dialogue_completion": "user", "max_turns": 2}
        )
    )
    with pytest.raises(ValidationError):
        await evaluator(bundle(), case)
    assert runner.target_sends == 1 and len(runner.user_requests) == 1
    assert not scorer.histories


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_kind", ["bool", "syntax", "missing_field", "empty_message"]
)
async def test_format_repair_does_not_repeat_target_or_score_and_keeps_original_user_context(
    monkeypatch, invalid_kind
):
    patch(monkeypatch)
    runner = InvalidUserRunner()
    runner.invalid_kind = invalid_kind
    scorer = Scorer()
    evaluator = measure(runner, scorer)
    case = (
        suite()
        .cases[0]
        .model_copy(
            update={
                "mode": "dialogue",
                "dialogue_completion": "user",
                "max_turns": 2,
                "user_context": "AUTHORIZED USER CONTEXT",
            }
        )
    )
    result = await evaluator(bundle(), case)
    assert runner.target_sends == 2 and len(runner.user_requests) == 2
    assert len(scorer.histories) == 1 and len(scorer.histories[0]) == 2
    assert result["grade"]["score"] == pytest.approx(0.4)
    assert result["grade"]["diagnosis"]
    assert (
        runner.user_requests[1]["data"]["original_data"]
        == runner.user_requests[0]["data"]
    )
    assert "validation_error" in runner.user_requests[1]["data"]
    assert "rubric" not in runner.user_requests[1]["data"]["original_data"]
    assert result["infrastructure_retries"]["dialogue_format"] == 1


@pytest.mark.asyncio
async def test_invalid_user_json_exhausts_three_repairs_without_fabricating_grade(
    monkeypatch,
):
    patch(monkeypatch)
    runner = InvalidUserRunner(True)
    scorer = Scorer()
    evaluator = measure(runner, scorer)
    case = (
        suite()
        .cases[0]
        .model_copy(
            update={"mode": "dialogue", "dialogue_completion": "user", "max_turns": 2}
        )
    )
    with pytest.raises(ValidationError) as failed:
        await evaluator(bundle(), case)
    assert (
        runner.target_sends == 1
        and len(runner.user_requests) == 3
        and not scorer.histories
    )
    assert failed.value.rsi_failure_metadata["phase"] == "dialogue"


@pytest.mark.asyncio
async def test_driver_with_tool_permissions_is_not_implicitly_retried(monkeypatch):
    patch(monkeypatch)
    runner = InvalidUserRunner(True)
    evaluator = measure(runner)
    package = evaluator.driver.package.model_copy(deep=True)
    package.manifest.agents["assistant"] = package.manifest.agents[
        "assistant"
    ].model_copy(update={"tools": ("file_write",)})
    evaluator.driver = evaluator.driver.model_copy(update={"package": package})
    with pytest.raises(ValidationError):
        await evaluator._ask(
            evaluator.driver,
            "Continue",
            {"user_context": "known"},
            OptimizationDialogueReply,
        )
    assert len(runner.user_requests) == 1


@pytest.mark.asyncio
async def test_error_checkpoint_recovery_preserves_completed_zero_and_only_runs_missing_slot():
    staged = vars(recovery_helper)
    old = record()
    complete(old["cases"][0], score=0)
    old["status"] = "error"
    old["cases"][1]["status"] = "error"
    old["cases"][1]["trials"][0].update(status="error", error_type="ValidationError")
    original = copy.deepcopy(old)
    called = []

    async def evaluate(package, case):
        called.append(case.id)
        return {"grade": {"score": 1, "passed": True, "rationale": "fresh"}}

    from tests.app.v2.desktop.test_rsi_test_recovery_observer import suite as test_suite

    observer = staged["resumable_human_test_observer"](
        baseline=bundle(),
        suite=test_suite(),
        evaluate=evaluate,
        publish=lambda _: None,
        completed_records=[old],
    )
    enqueue(observer)
    await observer.finish()
    assert called == ["b"] and observer.records[0]["status"] == "completed"
    assert observer.records[0]["scores"]["test"] == 0.5 and old == original


@pytest.mark.parametrize("checkpoint_status", ["cancelled", "running", "error"])
def test_pending_recovery_never_reexecutes_an_already_scored_diagnosis_error(
    checkpoint_status,
):
    staged = vars(recovery_helper)
    old = record()
    complete(old["cases"][0], score=0)
    old["status"] = checkpoint_status
    old["cases"][0]["trials"][0]["status"] = "error"
    old["cases"][0]["trials"][0]["diagnosis_status"] = "error"
    old["cases"][1]["trials"][0]["status"] = "error"
    from tests.app.v2.desktop.test_rsi_test_recovery_observer import suite as test_suite

    with pytest.raises(ValueError, match="diagnosis-only recovery"):
        staged["resumable_human_test_observer"](
            baseline=bundle(),
            suite=test_suite(),
            evaluate=None,
            publish=lambda _: None,
            completed_records=[old],
        )
