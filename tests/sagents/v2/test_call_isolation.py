import asyncio
import collections
import json
from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest
from sagents.v2.optimization.call_isolation import retry_call, settle_cases
from sagents.v2.optimization.contracts import (
    OptimizationCase,
    OptimizationSuite,
    OptimizationGrade,
    OptimizationObservation,
)
from sagents.v2.optimization.scoring import ScoringResult, ScorerDescriptor
from tests.sagents.v2.test_package_optimizer import (
    Runner,
    bundle,
    context,
    optimizer,
    suite,
)
from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner


@pytest.fixture(autouse=True)
def quick_retry(monkeypatch):
    async def pause(attempt):
        await asyncio.sleep(0)

    monkeypatch.setattr("sagents.v2.optimization.call_isolation.retry_delay", pause)


def isolated_optimizer(runner):
    result = optimizer(runner)
    for name in (
        "evaluator",
        "tuner",
        "reviewer",
        "suite_reviewer",
        "test_driver",
        "test_designer",
    ):
        agent = getattr(result, name)
        if agent:
            package = agent.package.model_copy(deep=True)
            package.manifest.agents[agent.agent_id] = package.manifest.agents[
                agent.agent_id
            ].model_copy(update={"tools": ()})
            setattr(result, name, agent.model_copy(update={"package": package}))
    return result


def options(tmp_path, **extra):
    return dict(
        context=context(),
        goal="Conversions",
        validation_case_count=None,
        suite=suite(),
        rounds=1,
        final_max_cases=0,
        call_retries=3,
        restart_incomplete=True,
        recovery_binding_id="isolation/v1",
        max_concurrency=2,
        journal_path=tmp_path / "audit.jsonl",
        **extra,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_exhausted_case_does_not_cancel_siblings_or_queued_cases_and_resume_reuses_successes(
    tmp_path, concurrency
):
    all_good = asyncio.Event()

    class Faulty(Runner):
        def __init__(self):
            super().__init__(proposals=[{"rationale": "Keep correct procedures"}])
            self.counts = collections.Counter()
            self.fail = True
            self.done = set()

        async def run(self, package, key, content, ctx):
            if package.manifest.metadata.id != "test.target":
                return await super().run(package, key, content, ctx)
            self.counts[(package.content_hash, content)] += 1
            if content == "bad" and self.fail:
                if concurrency == 2:
                    await all_good.wait()
                raise TimeoutError()
            answer = await super().run(package, key, content, ctx)
            self.done.add(content)
            if len(self.done) == 9:
                all_good.set()
            return answer

    data = OptimizationSuite(
        cases=tuple(
            OptimizationCase(
                id=f"c{i}",
                input="bad" if i == 0 else f"good-{i}",
                rubric="correct",
                split="validation" if i == 9 else "training",
            )
            for i in range(10)
        )
    )
    runner = Faulty()
    kwargs = options(tmp_path)
    kwargs["suite"] = data
    kwargs["max_concurrency"] = concurrency
    with pytest.raises(TimeoutError):
        await isolated_optimizer(runner).optimize(bundle(), **kwargs)
    events = [
        json.loads(line) for line in kwargs["journal_path"].read_text().splitlines()
    ]
    completed = [
        e["data"]["result"]["case"]["id"]
        for e in events
        if e["event"] == "case_completed"
    ]
    assert len(completed) == 9 and len(runner.done) == 9
    assert runner.counts[(bundle().content_hash, "bad")] == 4
    assert all(
        runner.counts[(bundle().content_hash, f"good-{i}")] == 1 for i in range(1, 10)
    )
    runner.fail = False
    kwargs.update(
        resume_from=kwargs["journal_path"], journal_path=tmp_path / "resumed.jsonl"
    )
    result = await isolated_optimizer(runner).optimize(bundle(), **kwargs)
    assert len(result.report.baseline.cases) == 10
    assert all(
        runner.counts[(bundle().content_hash, f"good-{i}")] == 1 for i in range(1, 10)
    )


@pytest.mark.asyncio
async def test_scorer_and_diagnosis_retry_reuse_target_and_preserve_zero_score(
    tmp_path,
):
    class Scorer:
        descriptor = ScorerDescriptor(id="fixed", name="Fixed", version="1")

        def __init__(self):
            self.calls = collections.Counter()

        async def score(self, r):
            self.calls[r.case.id] += 1
            if r.case.id == "train" and self.calls[r.case.id] == 1:
                raise RuntimeError("worker exited")
            return ScoringResult(
                grade=OptimizationGrade(
                    score=0, passed=False, rationale="Authoritative zero"
                )
            )

    class Diagnoser(DiagnosticRunner):
        def __init__(self):
            super().__init__()
            self.targets = 0
            self.failures = 0

        async def run(self, p, key, content, ctx):
            if p.manifest.metadata.id == "test.target":
                self.targets += 1
            elif p.manifest.metadata.id == "test.evaluator":
                request = json.loads(content)
                if (
                    request["response_schema"]["title"] == "OptimizationDiagnosis"
                    and self.failures == 0
                ):
                    self.failures += 1
                    raise RuntimeError("analysis interrupted")
            return await super().run(p, key, content, ctx)

    runner = Diagnoser()
    scorer = Scorer()
    kwargs = options(tmp_path)
    result = await isolated_optimizer(runner).optimize(
        bundle(), scorer=scorer, **kwargs
    )
    assert runner.targets == 2 and runner.failures == 1
    assert scorer.calls == {"train": 2, "holdout-secret": 1}
    assert all(
        c.grade.score == 0 and not c.grade.passed for c in result.report.baseline.cases
    )


@pytest.mark.asyncio
async def test_user_cancel_drains_active_calls_and_does_not_start_queue():
    entered = asyncio.Event()
    active = 0
    started = []
    closed = []

    async def work(case):
        nonlocal active
        started.append(case)
        active += 1
        if active == 2:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            closed.append(case)

    task = asyncio.create_task(settle_cases(range(10), work, max_concurrency=2))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0 and len(started) == len(closed) == 2


@pytest.mark.asyncio
async def test_permissions_do_not_retry_and_arbitrary_errors_are_bounded():
    counts = collections.Counter()

    async def denied():
        counts["denied"] += 1
        raise PermissionError()

    async def bad():
        counts["bad"] += 1
        raise RuntimeError()

    with pytest.raises(PermissionError):
        await retry_call(denied, retries=3)
    with pytest.raises(RuntimeError) as e:
        await retry_call(bad, retries=3)
    assert counts == {"denied": 1, "bad": 4} and e.value.rsi_local_retries_exhausted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", ["test.evaluator", "test.tuner", "test.reviewer", "test.suite-reviewer"]
)
async def test_internal_role_failure_retries_locally_without_replaying_target(
    role, tmp_path
):
    class Roles(Runner):
        failures = 0

        async def run(self, p, key, content, ctx):
            if p.manifest.metadata.id == role and self.failures == 0:
                self.failures += 1
                raise RuntimeError("role interrupted")
            return await super().run(p, key, content, ctx)

    runner = Roles()
    kwargs = options(tmp_path)
    await isolated_optimizer(runner).optimize(bundle(), **kwargs)
    assert runner.failures == 1 and len(runner.target_hashes) == 4
    events = [
        json.loads(line) for line in kwargs["journal_path"].read_text().splitlines()
    ]
    assert len([e for e in events if e["event"] == "agent_call_failed"]) == 1


@pytest.mark.asyncio
async def test_dialogue_execution_failure_reopens_only_its_disposable_case(tmp_path):
    from sagents.v2.optimization.runner import OPTIMIZATION_CASE
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner

    class Dialogues(DialogueRunner):
        def __init__(self):
            super().__init__()
            self.opens = collections.Counter()
            self.sends = collections.Counter()
            self.failed = False

        @asynccontextmanager
        async def conversation(self, *args):
            case = OPTIMIZATION_CASE.get()
            self.opens[case.id] += 1
            turn = 0

            async def send(content):
                nonlocal turn
                turn += 1
                self.sends[case.id] += 1
                if case.id == "train" and turn == 2 and not self.failed:
                    self.failed = True
                    raise TimeoutError()
                return OptimizationObservation(
                    state="completed", output=f"target-turn-{turn}"
                )

            yield SimpleNamespace(send=send)

    class Score:
        descriptor = ScorerDescriptor(id="fixed", name="Fixed", version="1")

        def __init__(self):
            self.calls = collections.Counter()

        async def score(self, r):
            self.calls[r.case.id] += 1
            return ScoringResult(
                grade=OptimizationGrade(score=0, passed=False, rationale="Fixed zero")
            )

    runner = Dialogues()
    scorer = Score()
    kwargs = options(tmp_path)
    kwargs["suite"] = suite().model_copy(
        update={
            "cases": tuple(
                c.model_copy(
                    update={
                        "mode": "dialogue",
                        "dialogue_completion": "user",
                        "max_turns": 3,
                    }
                )
                for c in suite().cases
            )
        }
    )
    await isolated_optimizer(runner).optimize(bundle(), scorer=scorer, **kwargs)
    assert runner.opens == {"train": 2, "holdout-secret": 1}
    assert runner.sends == {"train": 5, "holdout-secret": 3}
    assert scorer.calls == {"train": 1, "holdout-secret": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_phase", ["execution", "scoring", "evaluation"])
async def test_human_only_failure_retries_just_its_phase_and_keeps_authoritative_zero(
    failed_phase,
):
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner
    from sagents.v2.optimization.observer import IsolatedTestEvaluator

    class HumanRunner(DialogueRunner):
        def __init__(self):
            super().__init__()
            self.sends = 0
            self.analyses = 0

        @asynccontextmanager
        async def conversation(self, *args):
            async def send(content):
                self.sends += 1
                if failed_phase == "execution" and self.sends == 1:
                    raise RuntimeError("target call failed")
                return OptimizationObservation(state="completed", output="result")

            yield SimpleNamespace(send=send)

        async def run(self, p, key, content, ctx):
            request = json.loads(content)
            if (
                request.get("response_schema", {}).get("title")
                == "OptimizationDiagnosis"
            ):
                self.analyses += 1
                if failed_phase == "evaluation" and self.analyses == 1:
                    raise RuntimeError("diagnosis call failed")
            return await super().run(p, key, content, ctx)

    class Fixed:
        def __init__(self):
            self.calls = 0

        async def score(self, r):
            self.calls += 1
            if failed_phase == "scoring" and self.calls == 1:
                raise RuntimeError("worker crashed")
            return ScoringResult(
                grade=OptimizationGrade(score=0, passed=False, rationale="Fixed zero")
            )

    runner = HumanRunner()
    roles = isolated_optimizer(runner)
    scorer = Fixed()
    measure = IsolatedTestEvaluator(
        runner=runner,
        evaluator=roles.evaluator,
        driver=roles.test_driver,
        context=context(),
        goal="Accuracy",
        scorer=scorer,
        call_retries=3,
        max_transport_retries=0,
        retry_local_evaluations=True,
        restart_incomplete_dialogues=True,
    )
    result = await measure(bundle(), suite().cases[0])
    assert result["grade"]["score"] == 0 and result["grade"]["passed"] is False
    assert runner.sends == (2 if failed_phase == "execution" else 1)
    assert scorer.calls == (2 if failed_phase == "scoring" else 1)
    assert runner.analyses == (2 if failed_phase == "evaluation" else 1)


@pytest.mark.asyncio
async def test_typed_transport_keeps_twelve_retry_budget_without_restarting_siblings():
    from sagents.v2.optimization.recovery import OptimizationTransientFailure

    attempts = 0

    async def work():
        nonlocal attempts
        attempts += 1
        if attempts < 6:
            raise OptimizationTransientFailure()
        return "done"

    assert await retry_call(work, retries=3) == "done" and attempts == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [False, True])
async def test_restart_after_exhausted_diagnosis_reuses_existing_numeric_grade_and_execution(
    tmp_path, tamper
):
    class Fixed:
        descriptor = ScorerDescriptor(id="fixed", name="Fixed", version="1")

        def __init__(self):
            self.calls = collections.Counter()

        async def score(self, r):
            self.calls[r.case.id] += 1
            return ScoringResult(
                grade=OptimizationGrade(score=0, passed=False, rationale="Stable zero")
            )

    class Persistent(DiagnosticRunner):
        def __init__(self):
            super().__init__()
            self.fail = True
            self.targets = collections.Counter()

        async def run(self, p, key, content, ctx):
            if p.manifest.metadata.id == "test.target":
                self.targets[content] += 1
            elif p.manifest.metadata.id == "test.evaluator":
                request = json.loads(content)
                if (
                    request["response_schema"]["title"] == "OptimizationDiagnosis"
                    and request["data"]["case"]["id"] == "train"
                    and self.fail
                ):
                    raise RuntimeError("diagnosis repeatedly failed")
            return await super().run(p, key, content, ctx)

    runner = Persistent()
    scorer = Fixed()
    kwargs = options(tmp_path)
    with pytest.raises(RuntimeError):
        await isolated_optimizer(runner).optimize(bundle(), scorer=scorer, **kwargs)
    assert sum(scorer.calls.values()) == 2 and sum(runner.targets.values()) == 2
    if tamper:
        events = [
            json.loads(line) for line in kwargs["journal_path"].read_text().splitlines()
        ]
        target_id = next(
            e["data"]["call_id"]
            for e in events
            if e["event"] == "target_call_started" and e["data"]["case_id"] == "train"
        )
        for e in events:
            if (
                e["event"] == "target_call_completed"
                and e["data"]["call_id"] == target_id
            ):
                e["data"]["observation"]["output"] = "different execution"
        kwargs["journal_path"].write_text("".join(json.dumps(e) + "\n" for e in events))
    runner.fail = False
    kwargs.update(
        resume_from=kwargs["journal_path"], journal_path=tmp_path / "resumed.jsonl"
    )
    if tamper:
        with pytest.raises(ValueError, match="different execution"):
            await isolated_optimizer(runner).optimize(bundle(), scorer=scorer, **kwargs)
        assert sum(scorer.calls.values()) == 2 and sum(runner.targets.values()) == 2
        return
    result = await isolated_optimizer(runner).optimize(
        bundle(), scorer=scorer, **kwargs
    )
    assert sum(scorer.calls.values()) == 2 and sum(runner.targets.values()) == 2
    assert all(c.grade.score == 0 for c in result.report.baseline.cases)


@pytest.mark.asyncio
async def test_readonly_question_generation_retries_without_target_execution():
    from sagents.v2.optimization.generator import AgentPackageTestGenerator

    roles = isolated_optimizer(Runner())
    calls = []
    retries = []

    class Designer:
        async def run(self, *args):
            calls.append(True)
            if len(calls) < 3:
                raise RuntimeError("designer failed")
            return OptimizationObservation(
                state="completed", output=suite().model_dump_json()
            )

    generator = AgentPackageTestGenerator(
        runner=Designer(),
        designer=roles.evaluator,
        call_retries=3,
        on_retry=lambda attempt, error: retries.append(attempt),
    )
    result = await generator.generate(
        bundle(), context=context(), max_cases=2, case_count=2
    )
    assert len(result.cases) == 2 and len(calls) == 3 and retries == [1, 2]


@pytest.mark.asyncio
async def test_cancel_during_retry_backoff_starts_no_new_attempt(monkeypatch):
    entered = asyncio.Event()
    calls = []

    async def blocked_delay(attempt):
        entered.set()
        await asyncio.Event().wait()

    async def failed():
        calls.append(True)
        raise RuntimeError()

    monkeypatch.setattr(
        "sagents.v2.optimization.call_isolation.retry_delay", blocked_delay
    )
    task = asyncio.create_task(retry_call(failed, retries=3))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_disposable_case_start_failure_retries_locally(tmp_path):
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner
    from sagents.v2.optimization.runner import OPTIMIZATION_CASE

    class Startup(DialogueRunner):
        def __init__(self):
            super().__init__()
            self.opens = collections.Counter()

        @asynccontextmanager
        async def conversation(self, *args):
            case = OPTIMIZATION_CASE.get()
            self.opens[case.id] += 1
            if case.id == "train" and self.opens[case.id] == 1:
                raise RuntimeError("environment initialization failed")
            async with super().conversation(*args) as session:
                yield session

    runner = Startup()
    kwargs = options(tmp_path)
    kwargs["suite"] = suite().model_copy(
        update={
            "cases": tuple(
                c.model_copy(update={"mode": "dialogue", "max_turns": 1})
                for c in suite().cases
            )
        }
    )
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Scorer

    await isolated_optimizer(runner).optimize(bundle(), scorer=Scorer(), **kwargs)
    assert runner.opens == {"train": 2, "holdout-secret": 1}


@pytest.mark.asyncio
async def test_invalid_proposal_returns_to_feedback_repair_instead_of_silent_replay():
    from sagents.v2.optimization.optimizer import InvalidOptimizationProposal

    attempts = []

    async def invalid():
        attempts.append(True)
        raise InvalidOptimizationProposal("invalid edited package")

    with pytest.raises(InvalidOptimizationProposal):
        await retry_call(invalid, retries=3)
    assert len(attempts) == 1
