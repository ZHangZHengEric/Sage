from __future__ import annotations

import asyncio
import json

import pytest

from sagents.v2 import AgentPackageOptimizer, IsolatedOptimizationRunner
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.optimization import (
    OptimizationAgent,
    OptimizationCase,
    OptimizationConstraints,
    OptimizationObservation,
    OptimizationSuite,
)
from sagents.v2.package.presets import BuiltinPackageFactory


def bundle(name="target"):
    data = BuiltinPackageFactory.create(
        "assistant", package_id=f"test.{name}", model="test"
    ).model_dump(mode="json")
    data["agents"]["assistant"]["instructions"] = {"path": "prompts/base.md"}
    return AgentPackageBundle.model_validate(
        {
            "manifest": data,
            "files": {
                "prompts/base.md": "Do unit conversions. Never send messages.",
                "skills/units/SKILL.md": "Check units.",
            },
        }
    )


def context():
    return RequestContext(
        actor=ActorRef(principal_id="alice", principal_type=PrincipalType.USER)
    )


def suite():
    return OptimizationSuite(
        cases=(
            OptimizationCase(id="train", input="Convert 2 km", rubric="Meters"),
            OptimizationCase(
                id="holdout-secret",
                input="Convert 7 cm",
                rubric="Millimeters",
                split="validation",
            ),
        )
    )


class Runner:
    def __init__(self, proposals=None, scores=None):
        self.proposals = list(
            proposals
            or [
                {"rationale": "Check arithmetic", "instruction_guidance": "guidance-1"},
                {
                    "rationale": "Try shorter output",
                    "instruction_guidance": "guidance-2",
                },
                {"rationale": "Improve clarity", "instruction_guidance": "guidance-3"},
            ]
        )
        self.scores = scores or {
            "base": 0.4,
            "guidance-1": 0.6,
            "guidance-2": 0.5,
            "guidance-3": 0.8,
        }
        self.requests = []
        self.target_hashes = []

    async def run(self, package, agent_id, content, ctx):
        self.requests.append((package.manifest.metadata.id, content))
        name = package.manifest.metadata.id
        if name == "test.suite-reviewer":
            output = json.dumps(
                {"approved": True, "rationale": "Consistent fixed tests", "issues": []}
            )
        elif name == "test.reviewer":
            output = json.dumps(
                {
                    "approved": True,
                    "memorization_detected": False,
                    "goal_drift_detected": False,
                    "permission_drift_detected": False,
                    "rationale": "Generalizable change",
                }
            )
        elif name == "test.evaluator":
            request = json.loads(content)
            if request["task"].startswith("Design"):
                output = suite().model_dump_json()
            else:
                observed = request["data"]["observation"]["output"]
                score = self.scores[observed]
                if isinstance(score, dict):
                    score = score[request["data"]["case"]["split"]]
                output = json.dumps(
                    {
                        "score": score,
                        "passed": score >= 0.6,
                        "rationale": "Checked result",
                    }
                )
        elif name == "test.tuner":
            proposal = self.proposals.pop(0)
            output = proposal if isinstance(proposal, str) else json.dumps(proposal)
        else:
            self.target_hashes.append(package.content_hash)
            instructions = (
                package.resolved_manifest().agents[agent_id].instructions.inline
            )
            output = (
                instructions.split("Optimization guidance:\n")[-1]
                if "Optimization guidance:" in instructions
                else "base"
            )
        return OptimizationObservation(
            state="completed", output=output, input_tokens=10, output_tokens=5
        )


def optimizer(runner):
    return AgentPackageOptimizer(
        runner=runner,
        evaluator=OptimizationAgent(package=bundle("evaluator"), agent_id="assistant"),
        tuner=OptimizationAgent(package=bundle("tuner"), agent_id="assistant"),
        reviewer=OptimizationAgent(package=bundle("reviewer"), agent_id="assistant"),
        suite_reviewer=OptimizationAgent(
            package=bundle("suite-reviewer"), agent_id="assistant"
        ),
    )


@pytest.mark.asyncio
async def test_multiple_rounds_select_best_preserve_input_and_hide_holdout():
    target = bundle()
    initial = target.model_dump_json()
    runner = Runner()
    result = await optimizer(runner).optimize(
        target,
        context=context(),
        goal="Accurate conversions",
        rounds=3,
        suite=suite(),
        final_max_cases=0,
    )
    assert target.model_dump_json() == initial
    assert [round.accepted for round in result.report.rounds] == [True, False, True]
    assert (
        result.report.rounds[2].parent_hash
        == result.report.rounds[0].candidate_package.content_hash
    )
    assert result.report.selected.mean_score("validation") == 0.8
    assert result.report.baseline.mean_score("training") == 0.4
    assert result.report.improved
    assert len(runner.target_hashes) == 8  # baseline + three candidates, two cases each
    assert len(result.report.agent_calls) == 15  # eight grades + three proposals
    candidate = result.candidate_package
    instructions = candidate.manifest.agents["assistant"].instructions.inline
    assert instructions.startswith(target.files["prompts/base.md"])
    assert instructions.count("Optimization guidance:") == 1
    assert instructions.endswith("guidance-3")
    assert candidate.files == target.files
    assert candidate.manifest.metadata.version != target.manifest.metadata.version
    for name, request in runner.requests:
        if name == "test.tuner":
            assert "holdout-secret" not in request
            assert "Convert 7 cm" not in request
    assert result == type(result).model_validate_json(result.model_dump_json())


@pytest.mark.asyncio
async def test_generate_suite_once_and_reject_holdout_regression():
    runner = Runner(
        proposals=[{"rationale": "Optimize", "instruction_guidance": "guidance-1"}],
        scores={"base": 0.5, "guidance-1": {"training": 0.8, "validation": 0.4}},
    )
    result = await optimizer(runner).optimize(
        bundle(), context=context(), goal="Accuracy", rounds=1, final_max_cases=0
    )
    assert not result.report.improved
    assert result.candidate_package == bundle()
    assert result.report.rounds[0].reason == "Regression on case: holdout-secret"
    assert [call.role for call in result.report.agent_calls].count("test_design") == 1


@pytest.mark.asyncio
async def test_malformed_and_unauthorized_proposals_consume_rounds_without_running():
    runner = Runner(
        proposals=[
            "not json",
            {"rationale": "Overwrite base", "files": {"prompts/base.md": "bad"}},
            {"rationale": "Raise budget", "budgets": {"max_steps": 99}},
        ]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=3,
        suite=suite(),
        final_max_cases=0,
    )
    assert len(result.report.rounds) == 3
    assert all(
        not round.accepted and round.candidate_package is None
        for round in result.report.rounds
    )
    assert len(runner.target_hashes) == 2
    assert not result.report.improved


@pytest.mark.asyncio
async def test_allowed_skill_and_budget_changes_are_copies():
    runner = Runner(
        proposals=[
            {
                "rationale": "Improve",
                "instruction_guidance": "guidance-1",
                "files": {"skills/units/SKILL.md": "Verify conversion twice."},
                "budgets": {"max_steps": 6},
            }
        ]
    )
    original = bundle()
    result = await optimizer(runner).optimize(
        original,
        context=context(),
        goal="Accuracy",
        rounds=1,
        suite=suite(),
        constraints=OptimizationConstraints(
            editable_files=("skills/units/SKILL.md",),
            editable_budget_fields=("max_steps",),
        ),
        final_max_cases=0,
    )
    assert (
        result.candidate_package.files["skills/units/SKILL.md"]
        == "Verify conversion twice."
    )
    assert original.files["skills/units/SKILL.md"] == "Check units."
    assert result.candidate_package.manifest.agents["assistant"].budgets.max_steps == 6
    assert (
        result.candidate_package.manifest.agents["assistant"].tools
        == original.manifest.agents["assistant"].tools
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rounds", [0, -1, 101, True, 1.5])
async def test_invalid_round_count_before_calls(rounds):
    runner = Runner()
    with pytest.raises(ValueError, match="rounds"):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            rounds=rounds,
            final_max_cases=0,
        )
    assert not runner.requests


@pytest.mark.asyncio
async def test_timeout_and_cancellation_reach_runner():
    closed = asyncio.Event()
    started = asyncio.Event()

    class Blocking:
        async def run(self, *args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    with pytest.raises(TimeoutError):
        await optimizer(Blocking()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            call_timeout_seconds=0.01,
            final_max_cases=0,
        )
    assert closed.is_set()
    closed.clear()
    task = asyncio.create_task(
        optimizer(Blocking()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            final_max_cases=0,
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_runner_authorization_errors_are_not_retried_as_invalid_patches():
    class Denied(Runner):
        async def run(self, package, *args):
            if package.manifest.metadata.id == "test.tuner":
                raise ValueError("host denies tuner")
            return await super().run(package, *args)

    with pytest.raises(ValueError, match="host denies"):
        await optimizer(Denied()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            rounds=3,
            suite=suite(),
            final_max_cases=0,
        )


@pytest.mark.asyncio
async def test_native_runner_runs_real_v2_application_and_materializes_files(tmp_path):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
    )
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )

    paths = []
    grants = []

    async def authorize(action, package, ctx):
        grants.append((action, package.content_hash, ctx.actor.principal_id))

    def factory(package, root, ctx):
        paths.append(root)
        assert (root / "skills/units/SKILL.md").read_text() == package.files[
            "skills/units/SKILL.md"
        ]
        return (
            SAgentBuilder()
            .with_defaults(session_root=root / "sessions")
            .with_model_provider(
                ScriptedModelProvider(
                    (
                        ScriptedModelStep(
                            events=(
                                ModelStreamEvent(
                                    kind=ModelEventKind.COMPLETED,
                                    response=ModelResponse(
                                        response_id="answer",
                                        text="2 km = 2000 m",
                                        finish_reason="stop",
                                    ),
                                ),
                            )
                        ),
                    )
                )
            )
        )

    runner = IsolatedOptimizationRunner(
        builder_factory=factory, authorize=authorize, root=tmp_path
    )
    first = await runner.run(bundle(), "assistant", "Convert 2 km", context())
    second = await runner.run(bundle(), "assistant", "Convert 2 km", context())
    assert first.state == second.state == "completed"
    assert first.output == "2 km = 2000 m"
    assert first.evidence["session_id"] != second.evidence["session_id"]
    assert len(grants) == 2
    assert paths[0] != paths[1]
    assert all(not path.exists() for path in paths)


@pytest.mark.asyncio
async def test_native_runner_cancellation_closes_driver_and_removes_workspace(tmp_path):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider

    started = asyncio.Event()
    released = asyncio.Event()
    paths = []

    class WaitingModel(ScriptedModelProvider):
        async def _stream(self, request):
            started.set()
            try:
                await asyncio.Event().wait()
                yield  # async generator protocol; never reached
            finally:
                released.set()

    async def authorize(*args):
        pass

    def factory(package, root, ctx):
        paths.append(root)
        return (
            SAgentBuilder()
            .with_defaults(session_root=root / "sessions")
            .with_model_provider(WaitingModel(()))
        )

    runner = IsolatedOptimizationRunner(
        builder_factory=factory, authorize=authorize, root=tmp_path
    )
    task = asyncio.create_task(
        runner.run(bundle(), "assistant", "Convert units", context())
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert released.is_set()
    assert not paths[0].exists()


@pytest.mark.asyncio
async def test_target_failure_cannot_be_selected_and_internal_failure_aborts():
    class FailedTarget(Runner):
        async def run(self, package, *args):
            if package.manifest.metadata.id == "test.target":
                self.target_hashes.append(package.content_hash)
                return OptimizationObservation(state="failed", output="claimed success")
            return await super().run(package, *args)

    result = await optimizer(FailedTarget()).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=2,
        final_max_cases=0,
    )
    assert not result.report.improved
    assert all(case.grade.score == 0 for case in result.report.baseline.cases)
    assert all(not round.accepted for round in result.report.rounds)

    class FailedTuner(Runner):
        async def run(self, package, *args):
            if package.manifest.metadata.id == "test.tuner":
                return OptimizationObservation(state="suspended")
            return await super().run(package, *args)

    with pytest.raises(RuntimeError, match="tuning agent did not complete"):
        await optimizer(FailedTuner()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            final_max_cases=0,
        )


@pytest.mark.asyncio
async def test_noop_not_selected_despite_possible_stochastic_improvement():
    runner = Runner(
        proposals=[
            {
                "rationale": "Unchanged skill",
                "files": {"skills/units/SKILL.md": "Check units."},
            }
        ]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        constraints=OptimizationConstraints(editable_files=("skills/units/SKILL.md",)),
        final_max_cases=0,
    )
    assert result.report.rounds[0].candidate_package == bundle()
    assert result.report.rounds[0].evaluation_reused
    assert "No changes" in result.report.rounds[0].reason
    assert len(runner.target_hashes) == 2


@pytest.mark.asyncio
async def test_grader_nan_is_rejected_and_evaluation_does_not_continue():
    runner = Runner(scores={"base": float("nan")})
    with pytest.raises(ValueError):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            final_max_cases=0,
        )
    assert not any(name == "test.tuner" for name, _ in runner.requests)


@pytest.mark.asyncio
async def test_default_runs_five_rounds_and_overall_timeout_is_bounded():
    runner = Runner(
        proposals=[{"rationale": "try", "instruction_guidance": "guidance-1"}] * 5
    )
    result = await optimizer(runner).optimize(
        bundle(), context=context(), goal="Accuracy", suite=suite(), final_max_cases=0
    )
    assert result.report.requested_rounds == len(result.report.rounds) == 5

    class Blocking:
        async def run(self, *args):
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await optimizer(Blocking()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            timeout_seconds=0.01,
            call_timeout_seconds=1,
            final_max_cases=0,
        )


@pytest.mark.asyncio
async def test_suite_validation_and_protected_paths_before_execution():
    with pytest.raises(ValueError, match="training and validation"):
        OptimizationSuite(
            cases=(
                OptimizationCase(id="one", input="one", rubric="one"),
                OptimizationCase(id="two", input="two", rubric="two"),
            )
        )
    with pytest.raises(ValueError, match="unique"):
        OptimizationSuite(
            cases=(
                OptimizationCase(id="one", input="one", rubric="one"),
                OptimizationCase(
                    id="one", input="two", rubric="two", split="validation"
                ),
            )
        )
    runner = Runner()
    with pytest.raises(ValueError, match="base instruction files"):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            constraints=OptimizationConstraints(editable_files=("prompts/base.md",)),
            final_max_cases=0,
        )
    assert not runner.requests


@pytest.mark.asyncio
async def test_all_iterations_include_rejected_packages_and_full_evaluations():
    result = await optimizer(Runner()).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=3,
        suite=suite(),
        final_max_cases=0,
    )
    assert [item.iteration for item in result.iterations] == [0, 1, 2, 3]
    assert [item.iteration for item in result.iterations if item.recommended] == [3]
    assert result.iterations[2].package == result.report.rounds[1].candidate_package
    assert result.iterations[2].evaluation == result.report.rounds[1].evaluation
    assert result.iterations[0].package == bundle()
    assert set(result.report.internal_agents) == {
        "test_designer",
        "evaluator",
        "tuner",
        "reviewer",
        "suite_reviewer",
    }
    for call in result.report.agent_calls:
        assert call.request
        if call.role == "evaluation":
            assert call.case_id in {"train", "holdout-secret"}
    assert [
        call.round for call in result.report.agent_calls if call.role == "tuning"
    ] == [1, 2, 3]


@pytest.mark.asyncio
async def test_evaluation_agent_is_authoritative_and_mechanical_evidence_is_only_evidence():
    class WithCheck(Runner):
        async def run(self, *args):
            observed = await super().run(*args)
            return observed.model_copy(
                update={"evidence": {"objective_check": {"passed": False}}}
            )

    result = await optimizer(WithCheck()).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=1,
        suite=suite(),
        final_max_cases=0,
    )
    assert result.report.baseline.cases[0].grade.score == 0.4
    assert result.report.selected.cases[0].grade.score == 0.6
    assert result.report.selected.cases[0].grade.passed
    assert (
        result.report.selected.cases[0].observation.evidence["objective_check"][
            "passed"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_single_json_fence_accepted_without_extracting_arbitrary_prose():
    runner = Runner(
        proposals=[
            '```json\n{"rationale":"Improve","instruction_guidance":"guidance-1"}\n```'
        ]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=1,
        suite=suite(),
        final_max_cases=0,
    )
    assert result.report.improved


@pytest.mark.asyncio
async def test_saturated_training_does_not_block_validation_improvement():
    runner = Runner(
        proposals=[{"rationale": "Improve", "instruction_guidance": "guidance-1"}],
        scores={
            "base": {"training": 1.0, "validation": 0.4},
            "guidance-1": {"training": 1.0, "validation": 0.8},
        },
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=1,
        suite=suite(),
        final_max_cases=0,
    )
    assert result.report.improved
    assert result.report.selected.mean_score("validation") == 0.8


@pytest.mark.asyncio
async def test_tool_and_skill_selection_and_skill_creation_require_host_candidates():
    runner = Runner(
        proposals=[
            {
                "rationale": "Use a better tool and skill",
                "instruction_guidance": "guidance-1",
                "tools": ["calculator"],
                "skills": ["units-v2"],
                "files": {"skills/units-v2/SKILL.md": "Calculate exactly."},
            }
        ]
    )
    policy = OptimizationConstraints(
        allow_tool_changes=True,
        allow_skill_changes=True,
        tool_candidates={"calculator": "Exact arithmetic"},
        skill_candidates={"units-v2": "Unit conversions"},
        creatable_files=("skills/units-v2/SKILL.md",),
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=1,
        suite=suite(),
        constraints=policy,
        final_max_cases=0,
    )
    target = result.candidate_package.manifest.agents["assistant"]
    assert target.tools == ("calculator",)
    assert target.skills == ("units-v2",)
    assert (
        result.candidate_package.files["skills/units-v2/SKILL.md"]
        == "Calculate exactly."
    )
    assert "skills/units-v2/SKILL.md" not in bundle().files
    assert "Exact arithmetic" in next(
        content for name, content in runner.requests if name == "test.tuner"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch,policy",
    [
        ({"tools": ["calculator"]}, OptimizationConstraints()),
        (
            {"tools": ["shell"]},
            OptimizationConstraints(
                allow_tool_changes=True, tool_candidates={"calculator": "math"}
            ),
        ),
        ({"skills": ["unknown"]}, OptimizationConstraints(allow_skill_changes=True)),
    ],
)
async def test_unknown_capabilities_cannot_be_added(patch, policy):
    runner = Runner(proposals=[{"rationale": "Change", **patch}])
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=1,
        suite=suite(),
        constraints=policy,
        final_max_cases=0,
    )
    assert result.report.rounds[0].candidate_package is None
    assert len(runner.target_hashes) == 2


@pytest.mark.asyncio
async def test_unchanged_iterations_include_reused_test_records_and_one_recommendation():
    runner = Runner(proposals=[{"rationale": "Already sufficient"}] * 3)
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        rounds=3,
        suite=suite(),
        final_max_cases=0,
    )
    assert len(result.iterations) == 4
    assert all(item.evaluation_reused for item in result.iterations[1:])
    assert [item.iteration for item in result.iterations if item.recommended] == [0]
    assert len(runner.target_hashes) == 2


@pytest.mark.asyncio
async def test_standalone_test_generator_needs_no_target_execution_or_tuner():
    from sagents.v2 import AgentPackageTestGenerator

    runner = Runner()
    generator = AgentPackageTestGenerator(
        runner=runner,
        designer=OptimizationAgent(package=bundle("evaluator"), agent_id="assistant"),
    )
    original = bundle()
    record = await generator.generate_with_record(
        original, context=context(), max_cases=2
    )
    assert record.suite == suite()
    assert record.call.role == "test_design"
    assert len(runner.requests) == 1
    assert runner.requests[0][0] == "test.evaluator"
    assert not runner.target_hashes
    assert original == bundle()
    assert record == type(record).model_validate_json(record.model_dump_json())
    assert (
        await optimizer(Runner()).generate_test_suite(
            original, context=context(), max_cases=2
        )
        == suite()
    )


@pytest.mark.asyncio
async def test_tuner_gets_host_principles_in_system_without_changing_callers_package():
    from sagents.v2.optimization.principles import TUNING_PRINCIPLES

    configured = OptimizationAgent(package=bundle("tuner"), agent_id="assistant")
    before = configured.model_dump_json()
    opt = AgentPackageOptimizer(
        runner=Runner(),
        evaluator=OptimizationAgent(package=bundle("evaluator"), agent_id="assistant"),
        tuner=configured,
    )
    actual = (
        opt.tuner.package.resolved_manifest().agents["assistant"].instructions.inline
    )
    assert TUNING_PRINCIPLES in actual
    assert "Never copy test questions" in actual
    assert "A no-change round is legitimate" in actual
    assert configured.model_dump_json() == before


@pytest.mark.asyncio
async def test_opt_in_latency_improvement_preserves_quality():
    class Timed(Runner):
        async def run(self, package, *args):
            observed = await super().run(package, *args)
            if package.manifest.metadata.id == "test.target":
                guidance = (
                    package.resolved_manifest().agents["assistant"].instructions.inline
                )
                return observed.model_copy(
                    update={"elapsed_seconds": 1 if "guidance-1" in guidance else 10}
                )
            return observed

    runner = Timed(
        proposals=[{"rationale": "Faster", "instruction_guidance": "guidance-1"}],
        scores={"base": 1.0, "guidance-1": 1.0},
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Reduce latency",
        rounds=1,
        suite=suite(),
        min_latency_improvement=0.2,
        final_max_cases=0,
    )
    assert result.report.improved
    assert "latency improvement" in result.report.rounds[0].reason
    # Fast incorrect output must still be rejected.
    runner = Timed(
        proposals=[{"rationale": "Faster", "instruction_guidance": "guidance-1"}],
        scores={"base": 1.0, "guidance-1": 0.5},
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Reduce latency",
        rounds=1,
        suite=suite(),
        min_latency_improvement=0.2,
        final_max_cases=0,
    )
    assert not result.report.improved


@pytest.mark.asyncio
async def test_native_runner_preserves_tool_execution_evidence(tmp_path):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
        ModelToolCall,
    )
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )
    from sagents.v2.tool.decorators import tool
    from sagents.v2.tool.decorated import DecoratedToolProvider

    class Tools:
        @tool(description="Double an integer", plan_safe=True)
        async def double_value(self, value: int) -> int:
            return value * 2

    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["tools"] = ["double_value"]
    package = AgentPackageBundle.model_validate(data)

    async def authorize(*args):
        pass

    def factory(bundle, root, context):
        provider = DecoratedToolProvider(Tools())
        responses = (
            ModelResponse(
                response_id="call",
                tool_calls=(
                    ModelToolCall(
                        tool_call_id="double",
                        name="double_value",
                        arguments={"value": 2},
                    ),
                ),
                finish_reason="tool_calls",
            ),
            ModelResponse(response_id="answer", text="4", finish_reason="stop"),
        )
        model = ScriptedModelProvider(
            tuple(
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED, response=response
                        ),
                    )
                )
                for response in responses
            )
        )
        return (
            SAgentBuilder()
            .with_defaults(session_root=root / "sessions")
            .with_model_provider(model)
            .with_tool_provider(provider.catalog, provider.executor)
        )

    runner = IsolatedOptimizationRunner(
        builder_factory=factory, authorize=authorize, root=tmp_path
    )
    observation = await runner.run(package, "assistant", "Double 2", context())
    assert observation.output == "4"
    events = observation.evidence["runtime_events"]
    assert any(event["type"] == "tool.call.succeeded" for event in events)
    assert any(
        event["data"]["kind"] == "item"
        and event["data"]["item"]["data"]["kind"] == "tool_result"
        for event in events
    )
    assert not observation.evidence["runtime_events_truncated"]


@pytest.mark.asyncio
async def test_faster_but_still_failing_candidate_cannot_win_on_latency_alone():
    class FastFailure(Runner):
        async def run(self, package, *args):
            observation = await super().run(package, *args)
            changed = (
                "Optimization guidance:"
                in package.resolved_manifest().agents["assistant"].instructions.inline
            )
            return observation.model_copy(
                update={"elapsed_seconds": 1 if changed else 10}
            )

    runner = FastFailure(
        proposals=[{"rationale": "Faster", "instruction_guidance": "guidance-1"}],
        scores={"base": 0.0, "guidance-1": 0.0},
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Reduce latency",
        rounds=1,
        suite=suite(),
        min_latency_improvement=0.2,
        final_max_cases=0,
    )
    assert not result.report.improved


@pytest.mark.asyncio
async def test_dialogue_user_driver_and_evaluator_preserve_original_goal_and_turn_limit():
    from contextlib import asynccontextmanager

    class DialogueRunner(Runner):
        def __init__(self, finish_at):
            super().__init__(proposals=[{"rationale": "Already sufficient"}])
            self.finish_at = finish_at
            self.sessions = []

        @asynccontextmanager
        async def conversation(self, package, agent_id, ctx):
            sent = []
            self.sessions.append(sent)
            outer = self

            class Session:
                async def send(self, text):
                    sent.append(text)
                    return OptimizationObservation(
                        state="completed",
                        output="goal reached"
                        if len(sent) >= outer.finish_at
                        else "clarification?",
                        elapsed_seconds=1,
                    )

            yield Session()

        async def run(self, package, agent_id, content, ctx):
            request = json.loads(content)
            if request["task"].startswith("Continue this test"):
                assert "rubric" not in request["data"]
                return OptimizationObservation(
                    state="completed",
                    output=json.dumps(
                        {
                            "can_continue": True,
                            "message": "Known user fact",
                            "rationale": "Supplied context",
                        }
                    ),
                )
            if package.manifest.metadata.id == "test.evaluator":
                done = request["data"]["observation"]["output"] == "goal reached"
                assert request["data"]["case"]["input"] == "Original user goal"
                return OptimizationObservation(
                    state="completed",
                    output=json.dumps(
                        {
                            "score": int(done),
                            "passed": done,
                            "rationale": "Original goal judgment",
                        }
                    ),
                )
            return await super().run(package, agent_id, content, ctx)

    fixed = OptimizationSuite(
        cases=tuple(
            OptimizationCase(
                id=split,
                input="Original user goal",
                rubric="Reach the original goal",
                split=split,
                mode="dialogue",
                max_turns=3,
                user_context="Known user facts",
            )
            for split in ("training", "validation")
        )
    )
    runner = DialogueRunner(finish_at=2)
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Original goal",
        rounds=1,
        suite=fixed,
        final_max_cases=0,
    )
    assert all(
        case.stop_reason == "goal_achieved" and len(case.dialogue) == 2
        for case in result.report.baseline.cases
    )
    assert (
        len(runner.sessions) == 2
    )  # one isolated conversation per case; no-change reuses evaluations
    assert all(len(session) == 2 for session in runner.sessions)
    assert [call.role for call in result.report.agent_calls].count("test_dialogue") == 2
    runner = DialogueRunner(finish_at=99)
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Original goal",
        rounds=1,
        suite=fixed,
        final_max_cases=0,
    )
    assert all(
        case.stop_reason == "turn_limit"
        and not case.grade.passed
        and len(case.dialogue) == 3
        for case in result.report.baseline.cases
    )
    assert all(
        case.observation.elapsed_seconds == 3 for case in result.report.baseline.cases
    )


@pytest.mark.asyncio
async def test_native_conversation_keeps_target_session_and_prior_messages(tmp_path):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
    )
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )

    grants = []

    async def authorize(action, *args):
        grants.append(action)

    def factory(package, root, ctx):
        def sees_previous(request):
            assert "Remember the number 42" in request.model_dump_json()

        steps = tuple(
            ScriptedModelStep(
                assertion=sees_previous if index else None,
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id=f"r{index}", text=text, finish_reason="stop"
                        ),
                    ),
                ),
            )
            for index, text in enumerate(("Remembered", "42"))
        )
        return (
            SAgentBuilder()
            .with_defaults(session_root=root / "sessions")
            .with_model_provider(ScriptedModelProvider(steps))
        )

    runner = IsolatedOptimizationRunner(
        builder_factory=factory, authorize=authorize, root=tmp_path
    )
    async with runner.conversation(bundle(), "assistant", context()) as session:
        first = await session.send("Remember the number 42")
        second = await session.send("What number did I tell you?")
        assert first.evidence["session_id"] == second.evidence["session_id"]
        assert first.evidence["run_id"] != second.evidence["run_id"]
        assert second.output == "42"
    assert grants == ["optimize_run", "optimize_run"]
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_journal_keeps_candidate_and_outputs_when_candidate_grading_fails(
    tmp_path,
):
    class BrokenGrader(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.evaluator":
                request = json.loads(content)
                if request["data"]["observation"]["output"] == "guidance-1":
                    return OptimizationObservation(
                        state="completed", output="invalid grading JSON"
                    )
            return await super().run(package, agent_id, content, ctx)

    path = tmp_path / "audit.jsonl"
    runner = BrokenGrader()
    with pytest.raises(ValueError):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            rounds=1,
            journal_path=path,
            final_max_cases=0,
        )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["sequence"] for r in records] == list(range(1, len(records) + 1))
    assert records[-1]["data"]["status"] == "failed"
    assert len([r for r in records if r["event"] == "case_completed"]) == 2
    candidate = next(
        r["data"]["package"] for r in records if r["event"] == "candidate_created"
    )
    AgentPackageBundle.model_validate(candidate)
    assert any(
        r["event"] == "target_call_completed"
        and r["data"]["observation"]["output"] == "guidance-1"
        for r in records
    )
    assert any(
        r["event"] == "agent_call_completed"
        and r["data"]["observation"]["output"] == "invalid grading JSON"
        for r in records
    )
    assert len(runner.target_hashes) == 3  # never retries the failed evaluation
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_journal_refuses_overwrite_before_model_calls_and_records_complete_result(
    tmp_path,
):
    path = tmp_path / "audit.jsonl"
    runner = Runner(proposals=[{"rationale": "Sufficient"}])
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        journal_path=path,
        final_max_cases=0,
    )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert (
        type(result).model_validate(
            next(
                r["data"]["result"] for r in records if r["event"] == "result_completed"
            )
        )
        == result
    )
    assert records[-1]["data"]["status"] == "completed"
    before = path.read_bytes()
    unused = Runner()
    with pytest.raises(FileExistsError):
        await optimizer(unused).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            rounds=1,
            journal_path=path,
            final_max_cases=0,
        )
    assert path.read_bytes() == before
    assert not unused.requests


@pytest.mark.asyncio
async def test_cancelled_journal_marks_inflight_call_unknown_without_replay(tmp_path):
    started = asyncio.Event()

    class Blocked(Runner):
        async def run(self, *args):
            if args[0].manifest.metadata.id == "test.suite-reviewer":
                return await super().run(*args)
            started.set()
            await asyncio.Event().wait()

    path = tmp_path / "audit.jsonl"
    task = asyncio.create_task(
        optimizer(Blocked()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            journal_path=path,
            final_max_cases=0,
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[-1]["data"]["status"] == "cancelled"
    assert len([r for r in records if r["event"] == "target_call_started"]) == 1
    assert not any(r["event"] == "target_call_completed" for r in records)


@pytest.mark.asyncio
async def test_dialogue_setup_obeys_call_deadline_and_cleans_up():
    from contextlib import asynccontextmanager

    released = asyncio.Event()

    class BlockedSetup(Runner):
        @asynccontextmanager
        async def conversation(self, *args):
            try:
                await asyncio.Event().wait()
                yield
            finally:
                released.set()

    fixed = suite().model_copy(
        update={
            "cases": tuple(
                case.model_copy(update={"mode": "dialogue"}) for case in suite().cases
            )
        }
    )
    with pytest.raises(TimeoutError):
        await optimizer(BlockedSetup()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=fixed,
            call_timeout_seconds=0.01,
            timeout_seconds=10,
            final_max_cases=0,
        )
    assert released.is_set()


@pytest.mark.asyncio
async def test_repeated_trials_reject_lucky_candidate_and_retain_every_model_grade():
    class Unstable(Runner):
        def __init__(self):
            super().__init__(
                proposals=[
                    {"rationale": "Improve", "instruction_guidance": "guidance-1"}
                ],
                scores={"base": 0.4, "guidance-1": 0.8, "unstable": 0.2},
            )
            self.candidate_calls = 0

        async def run(self, package, *args):
            observation = await super().run(package, *args)
            if (
                package.manifest.metadata.id == "test.target"
                and observation.output == "guidance-1"
            ):
                self.candidate_calls += 1
                if self.candidate_calls > 2:
                    observation = observation.model_copy(update={"output": "unstable"})
            return observation.model_copy(update={"elapsed_seconds": 2, "cost": 0.1})

    runner = Unstable()
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        evaluation_repeats=2,
        final_max_cases=0,
    )
    assert len(runner.target_hashes) == 8  # two baseline/candidate trials per case
    assert not result.report.improved
    assert result.report.evaluation_repeats == 2
    for case in result.report.rounds[0].evaluation.cases:
        assert case.grade.score == 0.2 and not case.grade.passed
        assert (
            case.model_grade is None
        )  # aggregate is not an invented evaluator response
        assert [trial.model_grade.score for trial in case.trials] == [0.8, 0.2]
        assert case.observation.elapsed_seconds == 2  # average per execution
        assert case.observation.input_tokens == 20
        assert case.observation.cost == pytest.approx(0.2)  # all actual spend
    assert {
        call.trial for call in result.report.agent_calls if call.role == "evaluation"
    } == {1, 2}
    assert result == type(result).model_validate_json(result.model_dump_json())


@pytest.mark.asyncio
async def test_failed_repeat_cannot_be_hidden_by_successful_representative():
    class FailsLater(Runner):
        async def run(self, package, *args):
            observation = await super().run(package, *args)
            if (
                package.manifest.metadata.id == "test.target"
                and len(self.target_hashes) == 7
            ):
                return OptimizationObservation(state="failed")
            return observation

    result = await optimizer(FailsLater()).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        evaluation_repeats=2,
        final_max_cases=0,
    )
    assert not result.report.improved
    assert result.report.rounds[0].evaluation.cases[0].observation.state == "failed"
    assert not result.report.rounds[0].evaluation.cases[0].grade.passed


@pytest.mark.asyncio
@pytest.mark.parametrize("repeats", [0, 11, True, 1.5])
async def test_invalid_repeats_fail_before_calls(repeats):
    runner = Runner()
    with pytest.raises(ValueError, match="evaluation_repeats"):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            evaluation_repeats=repeats,
            final_max_cases=0,
        )
    assert not runner.requests


@pytest.mark.asyncio
async def test_host_evaluation_and_design_principles_preserve_configured_packages():
    from sagents.v2.optimization.principles import (
        EVALUATION_PRINCIPLES,
        DESIGN_PRINCIPLES,
    )
    from sagents.v2 import AgentPackageTestGenerator

    evaluator = OptimizationAgent(package=bundle("evaluator"), agent_id="assistant")
    before = evaluator.model_dump_json()
    opt = AgentPackageOptimizer(
        runner=Runner(),
        evaluator=evaluator,
        tuner=OptimizationAgent(package=bundle("tuner"), agent_id="assistant"),
    )
    assert (
        EVALUATION_PRINCIPLES
        in opt.evaluator.package.resolved_manifest()
        .agents["assistant"]
        .instructions.inline
    )
    generator = AgentPackageTestGenerator(runner=Runner(), designer=evaluator)
    assert (
        DESIGN_PRINCIPLES
        in generator.designer.package.resolved_manifest()
        .agents["assistant"]
        .instructions.inline
    )
    assert evaluator.model_dump_json() == before


@pytest.mark.asyncio
async def test_prompt_and_skill_growth_limits_reject_before_candidate_execution():
    runner = Runner(
        proposals=[
            {"rationale": "Too much guidance", "instruction_guidance": "123456"},
            {
                "rationale": "Too much Skill text",
                "files": {"skills/units/SKILL.md": "中文"},
            },
        ]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=2,
        constraints=OptimizationConstraints(
            max_guidance_chars=5,
            max_file_bytes=5,
            editable_files=("skills/units/SKILL.md",),
        ),
        final_max_cases=0,
    )
    assert len(runner.target_hashes) == 2
    assert "max_guidance_chars" in result.report.rounds[0].reason
    assert "max_file_bytes" in result.report.rounds[1].reason


@pytest.mark.asyncio
async def test_journal_keeps_invalid_designer_response(tmp_path):
    class BadDesigner(Runner):
        async def run(self, package, agent_id, content, ctx):
            return OptimizationObservation(
                state="completed", output="invalid suite JSON"
            )

    path = tmp_path / "audit.jsonl"
    with pytest.raises(ValueError):
        await optimizer(BadDesigner()).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            journal_path=path,
            final_max_cases=0,
        )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    call = next(
        r["data"]["call"] for r in records if r["event"] == "test_design_call_completed"
    )
    assert call["observation"]["output"] == "invalid suite JSON"
    assert json.loads(call["request"])["data"]["goal"] == "Accuracy"
    assert records[-1]["data"]["status"] == "failed"


def final_suite():
    from sagents.v2 import OptimizationFinalSuite

    return OptimizationFinalSuite(
        cases=(
            OptimizationCase(
                id="untouched-final",
                input="Convert 13 meters to centimeters",
                rubric="Exactly 1300 cm",
                split="final",
            ),
        )
    )


class FinalRunner(Runner):
    async def run(self, package, agent_id, content, ctx):
        if package.manifest.metadata.id == "test.evaluator":
            request = json.loads(content)
            if (
                request["task"].startswith("Design")
                and request["data"].get("phase") == "final"
            ):
                self.requests.append((package.manifest.metadata.id, content))
                return OptimizationObservation(
                    state="completed", output=final_suite().model_dump_json()
                )
        return await super().run(package, agent_id, content, ctx)


@pytest.mark.asyncio
async def test_default_sealed_final_stage_is_after_selection_and_hidden_from_tuner_and_reviewer():
    runner = FinalRunner(
        proposals=[{"rationale": "Generalize", "instruction_guidance": "guidance-1"}]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accurate conversions",
        suite=suite(),
        rounds=1,
    )
    final = result.report.final_verification
    assert final.passed and final.candidate_iteration == 1
    assert final.candidate.package_hash == result.candidate_package.content_hash
    assert final.baseline.package_hash == bundle().content_hash
    assert len(runner.target_hashes) == 6  # two baseline, two candidate, two final
    target_requests = [
        content for name, content in runner.requests if name == "test.target"
    ]
    assert target_requests[-2:] == [final_suite().cases[0].input] * 2
    assert result.report.rounds[0].review.approved
    for name, content in runner.requests:
        if name in {"test.tuner", "test.reviewer"}:
            assert "untouched-final" not in content
            assert "Convert 13 meters" not in content
    assert [c.phase for c in result.report.agent_calls if c.role == "evaluation"] == [
        "optimization"
    ] * 4 + ["final"] * 2
    assert result == type(result).model_validate_json(result.model_dump_json())


@pytest.mark.asyncio
async def test_rejected_semantic_candidates_keep_full_packages_without_execution():
    class Rejecting(FinalRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.reviewer":
                request = json.loads(content)
                guidance = request["data"]["patch"]["instruction_guidance"]
                return OptimizationObservation(
                    state="completed",
                    output=json.dumps(
                        {
                            "approved": False,
                            "memorization_detected": guidance == "memorize",
                            "goal_drift_detected": guidance == "change goal",
                            "permission_drift_detected": False,
                            "rationale": "Detected changed content: " + guidance,
                            "findings": [guidance],
                        }
                    ),
                )
            return await super().run(package, agent_id, content, ctx)

    runner = Rejecting(
        proposals=[
            {"rationale": "Bad", "instruction_guidance": "memorize"},
            {"rationale": "Bad", "instruction_guidance": "change goal"},
        ]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=2,
        final_suite=final_suite(),
    )
    assert (
        len(runner.target_hashes) == 3
    )  # only original tuning suite and final baseline
    assert result.report.final_verification.evaluation_reused
    assert len(result.iterations) == 3
    assert all(
        i.evaluation is None and not i.recommended for i in result.iterations[1:]
    )
    assert result.iterations[1].review.memorization_detected
    assert result.iterations[2].review.goal_drift_detected
    tuning = [
        json.loads(content) for name, content in runner.requests if name == "test.tuner"
    ]
    assert tuning[1]["data"]["previous_attempts"][0]["semantic_review"][
        "memorization_detected"
    ]
    assert result.candidate_package == bundle()


@pytest.mark.asyncio
@pytest.mark.parametrize("final_score", [0.2, 0.6])
async def test_final_failure_or_score_regression_withdraws_recommendation_without_retuning(
    final_score,
):
    class FinalRegression(FinalRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.evaluator":
                request = json.loads(content)
                if (
                    request["task"].startswith("Grade")
                    and request["data"]["case"]["split"] == "final"
                ):
                    score = (
                        0.8
                        if request["data"]["observation"]["output"] == "base"
                        else final_score
                    )
                    return OptimizationObservation(
                        state="completed",
                        output=json.dumps(
                            {
                                "score": score,
                                "passed": score >= 0.6,
                                "rationale": "Unseen final evidence",
                            }
                        ),
                    )
            return await super().run(package, agent_id, content, ctx)

    runner = FinalRegression(
        proposals=[{"rationale": "Improve", "instruction_guidance": "guidance-1"}]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        final_suite=final_suite(),
    )
    assert result.report.rounds[0].accepted  # provisional selection remains auditable
    assert not result.report.final_verification.passed
    assert result.report.final_verification.candidate_iteration == 1
    assert result.candidate_package == bundle() and not result.report.improved
    assert [i.iteration for i in result.iterations if i.recommended] == [0]
    assert len([c for c in result.report.agent_calls if c.role == "tuning"]) == 1
    assert result.iterations[1].evaluation.mean_score("validation") == 0.6


@pytest.mark.asyncio
async def test_final_test_repeats_preserve_every_trial_and_fresh_execution():
    runner = FinalRunner(
        proposals=[{"rationale": "Improve", "instruction_guidance": "guidance-1"}]
    )
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        final_suite=final_suite(),
        evaluation_repeats=2,
    )
    assert len(runner.target_hashes) == 12
    final = result.report.final_verification
    assert final.passed
    assert (
        len(final.baseline.cases[0].trials) == len(final.candidate.cases[0].trials) == 2
    )
    assert (
        len(
            [
                c
                for c in result.report.agent_calls
                if c.role == "evaluation" and c.phase == "final"
            ]
        )
        == 4
    )


@pytest.mark.asyncio
async def test_overlapping_final_cases_rejected_before_target_runs():
    from sagents.v2 import OptimizationFinalSuite

    runner = FinalRunner()
    overlap = OptimizationFinalSuite(
        cases=(
            suite()
            .cases[0]
            .model_copy(
                update={
                    "id": "different-id",
                    "input": "  Convert   2 km  ",
                    "split": "final",
                }
            ),
        )
    )
    with pytest.raises(ValueError, match="distinct"):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            final_suite=overlap,
        )
    assert not runner.target_hashes and not runner.requests


@pytest.mark.asyncio
async def test_review_is_cumulative_preserves_original_and_excludes_manifest_tests():
    runner = FinalRunner()
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=3,
        final_suite=final_suite(),
    )
    reviews = [
        json.loads(c.request)["data"]
        for c in result.report.agent_calls
        if c.role == "semantic_review"
    ]
    assert len(reviews) == 3
    assert all(
        r["original_instructions"] == bundle().files["prompts/base.md"] for r in reviews
    )
    assert (
        reviews[2]["current_package"] == reviews[1]["current_package"]
    )  # round two regressed
    for review in reviews:
        for key in ("original_package", "current_package", "candidate_package"):
            assert review[key]["manifest"]["tests"] == {"scenarios": [], "gates": {}}
        assert "holdout-secret" not in json.dumps(review)


@pytest.mark.asyncio
async def test_malformed_review_fails_closed_and_journal_preserves_proposal(tmp_path):
    class Malformed(FinalRunner):
        async def run(self, package, *args):
            if package.manifest.metadata.id == "test.reviewer":
                return OptimizationObservation(
                    state="completed", output='{"approved": true}'
                )
            return await super().run(package, *args)

    runner = Malformed()
    path = tmp_path / "audit.jsonl"
    with pytest.raises(ValueError):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            rounds=1,
            final_suite=final_suite(),
            journal_path=path,
        )
    assert len(runner.target_hashes) == 2
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(r["event"] == "candidate_created" for r in records)
    assert any(
        r["event"] == "agent_call_started" and r["data"]["role"] == "semantic_review"
        for r in records
    )
    assert records[-1]["data"]["status"] == "failed"


def test_inconsistent_semantic_approval_and_invalid_final_splits_rejected():
    from sagents.v2 import OptimizationProposalReview, OptimizationFinalSuite

    with pytest.raises(ValueError, match="cannot approve"):
        OptimizationProposalReview(
            approved=True,
            memorization_detected=True,
            goal_drift_detected=False,
            permission_drift_detected=False,
            rationale="Bad",
        )
    with pytest.raises(ValueError, match="split=final"):
        OptimizationFinalSuite(cases=(suite().cases[0],))
    with pytest.raises(ValueError, match="training and validation"):
        OptimizationSuite(
            cases=tuple(
                case.model_copy(update={"split": "final"}) for case in suite().cases
            )
        )


@pytest.mark.asyncio
async def test_reviewer_host_system_principles_do_not_mutate_callers_config():
    from sagents.v2.optimization.principles import REVIEW_PRINCIPLES

    configured = OptimizationAgent(package=bundle("reviewer"), agent_id="assistant")
    before = configured.model_dump_json()
    opt = AgentPackageOptimizer(
        runner=Runner(),
        evaluator=OptimizationAgent(package=bundle("evaluator"), agent_id="assistant"),
        tuner=OptimizationAgent(package=bundle("tuner"), agent_id="assistant"),
        reviewer=configured,
    )
    assert (
        REVIEW_PRINCIPLES
        in opt.reviewer.package.resolved_manifest()
        .agents["assistant"]
        .instructions.inline
    )
    assert configured.model_dump_json() == before


@pytest.mark.asyncio
async def test_final_generator_is_standalone_and_records_final_phase():
    from sagents.v2 import AgentPackageTestGenerator

    generator = AgentPackageTestGenerator(
        runner=FinalRunner(),
        designer=OptimizationAgent(package=bundle("evaluator"), agent_id="assistant"),
    )
    generation = await generator.generate_final_with_record(
        bundle(), context=context(), max_cases=1, excluded_cases=suite().cases
    )
    assert generation.suite == final_suite()
    assert generation.call.phase == "final"
    assert json.loads(generation.call.request)["data"]["phase"] == "final"


@pytest.mark.asyncio
async def test_skill_only_scope_rejects_other_parts_and_keeps_full_skill_candidate():
    original = bundle()
    data = original.model_dump(mode="json")
    data["files"]["settings.json"] = "{}"
    original = AgentPackageBundle.model_validate(data)
    runner = Runner(
        proposals=[
            {"rationale": "Out of scope", "instruction_guidance": "guidance-1"},
            {"rationale": "Out of scope", "tools": ["calculator"]},
            {"rationale": "Out of scope", "budgets": {"max_steps": 3}},
            {"rationale": "Out of scope", "files": {"settings.json": "changed"}},
            {
                "rationale": "Reusable Skill",
                "files": {"skills/units/SKILL.md": "Validate units before conversion."},
                "skills": ["units"],
            },
        ]
    )
    result = await optimizer(runner).optimize(
        original,
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=5,
        optimization_scope=("skills",),
        final_max_cases=0,
        constraints=OptimizationConstraints(
            editable_files=("skills/units/SKILL.md", "settings.json"),
            allow_tool_changes=True,
            tool_candidates={"calculator": "Exact math"},
            allow_skill_changes=True,
            skill_candidates={"units": "Reusable conversion"},
            editable_budget_fields=("max_steps",),
        ),
    )
    assert all(r.candidate_package is None for r in result.report.rounds[:4])
    last = result.iterations[-1].package
    assert (
        last.manifest.agents["assistant"].instructions
        == original.manifest.agents["assistant"].instructions
    )
    assert (
        last.manifest.agents["assistant"].tools
        == original.manifest.agents["assistant"].tools
    )
    assert (
        last.manifest.agents["assistant"].budgets
        == original.manifest.agents["assistant"].budgets
    )
    assert last.files["settings.json"] == "{}"
    assert last.files["skills/units/SKILL.md"] == "Validate units before conversion."
    assert last.manifest.agents["assistant"].skills == ("units",)
    assert result.report.optimization_scope == ("skills",)
    tuner_requests = [
        json.loads(content) for name, content in runner.requests if name == "test.tuner"
    ]
    assert all(r["data"]["optimization_scope"] == ["skills"] for r in tuner_requests)
    assert all(
        not r["data"]["constraints"]["allow_instruction_guidance"]
        and not r["data"]["constraints"]["allow_tool_changes"]
        for r in tuner_requests
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,patch",
    [
        (("instructions",), {"instruction_guidance": "guidance-1"}),
        (("tools",), {"tools": ["calculator"]}),
        (("budgets",), {"budgets": {"max_steps": 3}}),
        (("resources",), {"files": {"settings.json": "changed"}}),
    ],
)
async def test_individual_optimization_scopes_allow_only_granted_parts(scope, patch):
    data = bundle().model_dump(mode="json")
    data["files"]["settings.json"] = "{}"
    original = AgentPackageBundle.model_validate(data)
    result = await optimizer(
        Runner(proposals=[{"rationale": "Scoped change", **patch}])
    ).optimize(
        original,
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=1,
        final_max_cases=0,
        optimization_scope=scope,
        constraints=OptimizationConstraints(
            editable_files=("settings.json",),
            allow_tool_changes=True,
            tool_candidates={"calculator": "Math"},
            editable_budget_fields=("max_steps",),
        ),
    )
    assert result.report.rounds[0].candidate_package is not None
    assert result.report.rounds[0].review.approved


@pytest.mark.asyncio
async def test_skill_scope_recognizes_nonstandard_skill_roots_and_cannot_expand_host_grants():
    data = bundle().model_dump(mode="json")
    data["files"].update(
        {
            "procedures/units/SKILL.md": "Reusable procedure",
            "procedures/units/helper.py": "before",
        }
    )
    original = AgentPackageBundle.model_validate(data)
    runner = Runner(
        proposals=[
            {
                "rationale": "Edit helper",
                "files": {"procedures/units/helper.py": "after"},
            },
            {"rationale": "Try unauthorized skill list", "skills": ["units"]},
        ]
    )
    result = await optimizer(runner).optimize(
        original,
        context=context(),
        goal="Accuracy",
        suite=suite(),
        rounds=2,
        final_max_cases=0,
        optimization_scope=("skills",),
        constraints=OptimizationConstraints(
            editable_files=("procedures/units/helper.py",),
            skill_candidates={"units": "Needs explicit selection grant"},
        ),
    )
    assert result.iterations[1].package.files["procedures/units/helper.py"] == "after"
    assert result.report.rounds[1].candidate_package is None
    assert "selection is not editable" in result.report.rounds[1].reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope", [(), ("unknown",), ("skills", "skills"), "skills", [1], [{}]]
)
async def test_invalid_optimization_scope_before_any_model_call(scope):
    runner = Runner()
    with pytest.raises(ValueError, match="optimization_scope"):
        await optimizer(runner).optimize(
            bundle(), context=context(), goal="Accuracy", optimization_scope=scope
        )
    assert not runner.requests


@pytest.mark.asyncio
async def test_suite_review_blocks_before_any_target_or_tuner_and_preserves_record(
    tmp_path,
):
    from sagents.v2 import OptimizationSuiteReviewRejected

    class Reject(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.suite-reviewer":
                self.requests.append((package.manifest.metadata.id, content))
                return OptimizationObservation(
                    state="completed",
                    output=json.dumps(
                        {
                            "approved": False,
                            "rationale": "Rubric adds an unstated obligation",
                            "issues": [
                                {
                                    "kind": "goal_conflict",
                                    "severity": "blocking",
                                    "case_ids": ["untouched-final"],
                                    "rationale": "Requires an unauthorized action",
                                    "suggested_fix": "Align the rubric with authorized conversions",
                                }
                            ],
                        }
                    ),
                )
            return await super().run(package, agent_id, content, ctx)

    runner = Reject()
    path = tmp_path / "audit.jsonl"
    with pytest.raises(OptimizationSuiteReviewRejected) as caught:
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Conversions only",
            suite=suite(),
            final_suite=final_suite(),
            rounds=2,
            journal_path=path,
        )
    assert not runner.target_hashes
    assert all(name == "test.suite-reviewer" for name, _ in runner.requests)
    assert caught.value.review.issues[0].case_ids == ("untouched-final",)
    assert caught.value.call.role == "suite_review"
    request = json.loads(caught.value.call.request)
    assert request["data"]["final_suite"]["cases"][0]["id"] == "untouched-final"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(
        e["event"] == "suite_review_completed" and not e["data"]["review"]["approved"]
        for e in events
    )
    assert not any(e["event"] == "target_call_started" for e in events)
    assert events[-1]["data"]["status"] == "failed"


@pytest.mark.parametrize(
    "output",
    [
        "invalid JSON",
        json.dumps(
            {
                "approved": True,
                "rationale": "Okay",
                "issues": [
                    {
                        "kind": "goal_conflict",
                        "severity": "blocking",
                        "rationale": "Conflict",
                        "suggested_fix": "Fix",
                    }
                ],
            }
        ),
        json.dumps({"approved": False, "rationale": "Bad", "issues": []}),
        json.dumps(
            {
                "approved": False,
                "rationale": "Bad",
                "issues": [
                    {
                        "kind": "goal_conflict",
                        "severity": "blocking",
                        "case_ids": ["invented-case"],
                        "rationale": "Conflict",
                        "suggested_fix": "Fix",
                    }
                ],
            }
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_suite_review_fails_closed(output):
    class Invalid(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.suite-reviewer":
                return OptimizationObservation(state="completed", output=output)
            return await super().run(package, agent_id, content, ctx)

    runner = Invalid()
    with pytest.raises(ValueError):
        await optimizer(runner).optimize(
            bundle(),
            context=context(),
            goal="Accuracy",
            suite=suite(),
            final_max_cases=0,
        )
    assert not runner.target_hashes
    assert not any(name == "test.tuner" for name, _ in runner.requests)


@pytest.mark.asyncio
async def test_advisory_suite_review_is_retained_and_does_not_leak_final_to_tuner():
    class Advisory(FinalRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.suite-reviewer":
                self.requests.append((package.manifest.metadata.id, content))
                return OptimizationObservation(
                    state="completed",
                    output=json.dumps(
                        {
                            "approved": True,
                            "rationale": "Consistent; coverage could be broader",
                            "issues": [
                                {
                                    "kind": "coverage_gap",
                                    "severity": "advisory",
                                    "case_ids": [],
                                    "rationale": "Small sample",
                                    "suggested_fix": "Add varied conversions",
                                }
                            ],
                        }
                    ),
                )
            return await super().run(package, agent_id, content, ctx)

    runner = Advisory()
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        final_suite=final_suite(),
        rounds=1,
    )
    assert result.report.suite_review.approved
    assert result.report.suite_review.issues[0].severity == "advisory"
    assert result.report.agent_calls[0].role == "suite_review"
    for name, request in runner.requests:
        if name in ("test.tuner", "test.reviewer"):
            assert "untouched-final" not in request
            assert "Convert 13 meters" not in request


@pytest.mark.asyncio
async def test_model_training_feedback_is_bounded_but_report_stays_lossless():
    from sagents.v2.optimization.feedback import training_feedback
    from sagents.v2.optimization import OptimizationCaseResult, OptimizationGrade

    noisy = OptimizationCaseResult(
        case=suite().cases[0],
        observation=OptimizationObservation(
            state="completed",
            output="answer" * 3000,
            evidence={
                "session_id": "session-1",
                "runtime_events": [
                    {
                        "type": "tool",
                        "data": {"kind": "tool_result", "output": "large" * 50000},
                    }
                ],
            },
        ),
        grade=OptimizationGrade(score=0, passed=False, rationale="Wrong"),
    )
    before = noisy.model_dump_json()
    feedback = training_feedback(noisy)
    assert noisy.model_dump_json() == before
    assert len(json.dumps(feedback)) < 8000
    assert feedback["observation"]["output_truncated"]
    assert feedback["observation"]["evidence"]["evidence_summarized"]
    assert feedback["observation"]["evidence"]["session_id"] == "session-1"
    assert feedback["observation"]["evidence"]["tool_events"][0]["truncated"]


@pytest.mark.asyncio
async def test_tuner_history_is_bounded_and_omission_is_explicit():
    runner = Runner(proposals=[{"rationale": "No justified change"}] * 7)
    result = await optimizer(runner).optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        final_max_cases=0,
        rounds=7,
    )
    assert len(result.report.rounds) == 7
    requests = [
        json.loads(content)["data"]
        for name, content in runner.requests
        if name == "test.tuner"
    ]
    assert len(requests[-1]["previous_attempts"]) == 4
    assert requests[-1]["previous_attempts_omitted"] == 2
    assert [item["round"] for item in requests[-1]["previous_attempts"]] == [3, 4, 5, 6]
