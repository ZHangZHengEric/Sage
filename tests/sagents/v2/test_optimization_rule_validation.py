"""Default candidate checks are deterministic and feed failures to the tuner."""
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationAgent, OptimizationConstraints
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, suite


def engine(runner, **options):
    return AgentPackageOptimizer(
        require_experiment=False,
        runner=runner,
        evaluator=OptimizationAgent(package=bundle("evaluator"), agent_id="assistant"),
        tuner=OptimizationAgent(package=bundle("tuner"), agent_id="assistant"),
        **options,
    )


async def optimize(opt, **options):
    return await opt.optimize(bundle(), context=context(), goal="Accuracy", suite=suite(),
                              rounds=1, validation_case_count=None, final_max_cases=0, **options)


@pytest.mark.asyncio
async def test_default_uses_no_candidate_review_model_and_repairs_scope_error_in_same_round(tmp_path):
    runner = Runner(proposals=[
        {"rationale": "Unpermitted capability", "tools": ["unavailable"]},
        {"rationale": "Fix using granted instructions", "instruction_guidance": "guidance-1"},
    ])
    opt = engine(runner)
    assert opt.reviewer is None
    journal = tmp_path / "audit.jsonl"
    result = await optimize(opt, journal_path=journal)
    round = result.report.rounds[0]
    assert round.accepted and round.review is None
    assert len(result.report.rounds) == 1
    assert "reviewer" not in result.report.internal_agents
    tuning = [json.loads(content) for name, content in runner.requests if name == "test.tuner"]
    assert len(tuning) == 2
    assert "tools selection is not editable" in tuning[1]["data"]["validation_error"]
    assert tuning[1]["data"]["repair"] == 1
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert any(e["event"] == "package_validation_failed" for e in events)
    assert any(e["event"] == "package_validation_passed" for e in events)
    assert not any(c.role == "semantic_review" for c in result.report.agent_calls)
    assert not any(e["event"] == "semantic_review_completed" for e in events)
    assert opt.suite_reviewer is None
    assert result.report.suite_review is None
    assert not any(c.role == "suite_review" for c in result.report.agent_calls)
    assert any(e["event"] == "dataset_validation_completed" for e in events)


@pytest.mark.asyncio
async def test_exhausted_rule_repairs_reject_without_executing_invalid_candidate():
    runner = Runner(proposals=[{"rationale": "Invalid", "tools": ["unavailable"]}] * 2)
    result = await optimize(engine(runner), max_edit_repairs=1)
    round = result.report.rounds[0]
    assert not round.accepted and round.review is None
    assert round.evaluation is None and round.candidate_package is None
    assert "after 1 repairs" in round.reason
    assert "tools selection is not editable" in round.reason
    assert set(runner.target_hashes) == {bundle().content_hash}


@pytest.mark.asyncio
async def test_skill_identity_failure_is_returned_to_tuner_then_validated_again():
    content = "---\nname: verify-units\ndescription: Check dimensions before converting units.\n---\nCheck dimension and scale."
    runner = Runner(proposals=[
        {"rationale": "Wrong metadata", "skills": ["verify-units"],
         "skill_definitions": {"verify-units": content.replace("name: verify-units", "name: rsi-guidance")}},
        {"rationale": "Correct identity", "instruction_guidance": "guidance-1", "skills": ["verify-units"],
         "skill_definitions": {"verify-units": content}},
    ])
    result = await optimize(engine(runner), constraints=OptimizationConstraints(
        allow_skill_changes=True, allow_skill_creation=True))
    assert result.report.rounds[0].accepted
    assert result.candidate_package.files["skills/verify-units/SKILL.md"] == content
    tuning = [json.loads(c) for n, c in runner.requests if n == "test.tuner"]
    assert "must match its directory" in tuning[1]["data"]["validation_error"]


@pytest.mark.asyncio
async def test_resume_refuses_candidate_review_policy_drift(tmp_path):
    journal = tmp_path / "audit.jsonl"
    await optimize(engine(Runner()), journal_path=journal, recovery_binding_id="fixed-host")
    replay = Runner()
    opt = engine(replay, reviewer=OptimizationAgent(package=bundle("reviewer"), agent_id="assistant"))
    with pytest.raises(ValueError, match="configuration"):
        await optimize(opt, resume_from=journal, recovery_binding_id="fixed-host")
    assert not replay.requests


@pytest.mark.asyncio
async def test_malformed_json_and_scope_errors_share_one_repair_budget():
    runner = Runner(proposals=[
        "not JSON",
        {"rationale": "Still invalid", "tools": ["unavailable"]},
    ])
    result = await optimize(engine(runner), max_edit_repairs=1)
    round = result.report.rounds[0]
    assert not round.accepted and round.evaluation is None
    tuning = [json.loads(c) for n, c in runner.requests if n == "test.tuner"]
    assert len(tuning) == 2
    assert tuning[1]["data"]["invalid_response"] == "not JSON"
    assert "after 1 repairs" in round.reason


@pytest.mark.asyncio
async def test_malformed_json_can_be_corrected_without_losing_round():
    runner = Runner(proposals=["not JSON", {"rationale": "Correct format", "instruction_guidance": "guidance-1"}])
    result = await optimize(engine(runner), max_edit_repairs=1)
    assert result.report.rounds[0].accepted


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_generated_schema_errors_return_to_designer_and_keep_failed_records(repair_succeeds):
    from sagents.v2.optimization.generator import AgentPackageTestGenerator
    from sagents.v2.optimization.contracts import OptimizationObservation

    class Designer:
        def __init__(self):
            self.requests = []

        async def run(self, package, agent_id, content, ctx):
            self.requests.append((package.manifest.metadata.id, json.loads(content)))
            case = {"id": "a", "input": "Convert 1 km", "split": "training"}
            if repair_succeeds and len(self.requests) > 1:
                case["rubric"] = "1000 meters"
            return OptimizationObservation(state="completed", output=json.dumps({"cases": [case]}))

    runner = Designer()
    generator = AgentPackageTestGenerator(runner=runner, validation_repairs=1,
        designer=OptimizationAgent(package=bundle("designer"), agent_id="assistant"))
    records = []
    async def generate():
        return await generator.generate_split_with_record(bundle(), context=context(), split="training",
            case_count=1, max_cases=1, on_call=records.append)
    if repair_succeeds:
        generated = await generate()
        assert generated.suite.cases[0].rubric == "1000 meters"
    else:
        with pytest.raises(ValueError, match="after 1 repairs"):
            await generate()
    assert len(records) == 2
    assert "rubric" not in json.loads(records[0].observation.output)["cases"][0]
    assert "rubric" in runner.requests[1][1]["data"]["validation_error"]
    assert {name for name, _ in runner.requests} == {"test.designer"}
