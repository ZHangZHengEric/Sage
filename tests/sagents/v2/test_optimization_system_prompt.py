"""Whole-prompt rewrites are isolated, scoped and semantically reviewed."""
import json

import pytest

from sagents.v2.optimization import OptimizationConstraints, OptimizationObservation
from sagents.v2.optimization.contracts import OptimizationPatch
from sagents.v2.optimization.optimizer import AgentPackageOptimizer, NoOptimizationChange
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite

PROMPT = "Convert units accurately. Verify scale factors. Never send messages."


def apply(patch, policy=None, current=None):
    original = bundle()
    return AgentPackageOptimizer._apply(
        original, current or original, "assistant", patch,
        policy or OptimizationConstraints(allow_instruction_guidance=False), "2",
    )


def test_whole_prompt_replaces_inline_without_mutating_baseline_or_other_artifacts():
    original = bundle()
    before = original.model_dump_json()
    candidate = AgentPackageOptimizer._apply(
        original, original, "assistant", OptimizationPatch(rationale="Clarify steps", system_prompt=PROMPT),
        OptimizationConstraints(allow_instruction_guidance=False), "2",
    )
    assert candidate.resolved_manifest().agents["assistant"].instructions.inline == PROMPT
    assert candidate.files == original.files
    assert original.model_dump_json() == before
    next_prompt = "Convert units. Check arithmetic and scale factors. Never send messages."
    second = apply(OptimizationPatch(rationale="Consolidate", system_prompt=next_prompt), current=candidate)
    assert second.resolved_manifest().agents["assistant"].instructions.inline == next_prompt
    assert "Optimization guidance:" not in second.model_dump_json()
    assert OptimizationPatch.model_validate_json(OptimizationPatch(rationale="Rewrite", system_prompt=PROMPT).model_dump_json()).system_prompt == PROMPT


@pytest.mark.parametrize("values", [
    {"system_prompt": " "},
    {"system_prompt": PROMPT, "instruction_guidance": "append"},
])
def test_prompt_rejects_empty_or_ambiguous_proposals(values):
    with pytest.raises(ValueError):
        OptimizationPatch(rationale="test", **values)


@pytest.mark.parametrize("policy,match", [
    (OptimizationConstraints(allow_system_prompt=False), "not editable"),
    (OptimizationConstraints(max_system_prompt_chars=4), "max_system_prompt_chars"),
])
def test_prompt_permissions_and_limits(policy, match):
    with pytest.raises(ValueError, match=match):
        apply(OptimizationPatch(rationale="test", system_prompt=PROMPT), policy)


def test_scope_disables_rewrite_and_unchanged_prompt_is_noop():
    policy = AgentPackageOptimizer._scope_constraints(bundle(), OptimizationConstraints(), ("skills",))
    assert not policy.allow_system_prompt and not policy.allow_instruction_guidance
    with pytest.raises(ValueError, match="not editable"):
        apply(OptimizationPatch(rationale="test", system_prompt=PROMPT), policy)
    with pytest.raises(NoOptimizationChange):
        candidate = apply(OptimizationPatch(rationale="test", system_prompt=PROMPT))
        apply(OptimizationPatch(rationale="unchanged", system_prompt=PROMPT), current=candidate)
    with pytest.raises(ValueError, match="guidance is not editable"):
        apply(OptimizationPatch(rationale="legacy", instruction_guidance="append"))


class RewriteRunner(Runner):
    async def run(self, package, agent_id, content, ctx):
        if package.manifest.metadata.id == "test.target":
            prompt = package.resolved_manifest().agents[agent_id].instructions.inline
            return OptimizationObservation(state="completed", output="guidance-1" if prompt == PROMPT else "base")
        if package.manifest.metadata.id == "test.reviewer":
            request = json.loads(content)
            candidate = request["data"]["candidate_package"]["manifest"]["agents"][agent_id]["instructions"]["inline"]
            approved = "Never send messages." in candidate
            self.requests.append((package.manifest.metadata.id, content))
            return OptimizationObservation(state="completed", output=json.dumps({
                "approved": approved, "goal_drift_detected": False,
                "permission_drift_detected": not approved,
                "rationale": "Original no-send boundary preserved" if approved else "Missing no-send boundary",
            }))
        return await super().run(package, agent_id, content, ctx)


@pytest.mark.asyncio
async def test_whole_rewrite_review_accepts_reorganization_and_rejects_permission_loss():
    runner = RewriteRunner(proposals=[
        {"rationale": "Make unit checks explicit", "system_prompt": PROMPT},
        {"rationale": "Drop prohibition", "system_prompt": "Convert units and send messages."},
    ])
    original = bundle()
    result = await optimizer(runner).optimize(
        original, context=context(), goal="Accurate conversions", suite=suite(),
        rounds=2, validation_case_count=None, final_max_cases=0,
        constraints=OptimizationConstraints(allow_instruction_guidance=False),
    )
    assert result.report.rounds[0].accepted
    assert not result.report.rounds[1].accepted
    assert "Semantic review rejected" in result.report.rounds[1].reason
    assert result.candidate_package.resolved_manifest().agents["assistant"].instructions.inline == PROMPT
    assert original.resolved_manifest().agents["assistant"].instructions.inline == "Do unit conversions. Never send messages."
    tuner_request = json.loads(next(content for name, content in runner.requests if name == "test.tuner"))
    assert tuner_request["data"]["original_instructions"] == original.resolved_manifest().agents["assistant"].instructions.inline
    assert "COMPLETE replacement" in tuner_request["task"]


@pytest.mark.parametrize('field,limit,match', [('max_skill_chars', 4, 'SKILL.md character counts'), ('max_skill_count', 0, 'max_skill_count=0')])
def test_skill_resource_limits_apply_to_complete_candidate(field, limit, match):
    with pytest.raises(ValueError, match=match):
        apply(OptimizationPatch(rationale='Rewrite', system_prompt=PROMPT),
            OptimizationConstraints(**{field: limit}))


@pytest.mark.parametrize('role', ['evaluator', 'tuner', 'reviewer', 'suite_reviewer', 'test_designer'])
def test_internal_roles_share_separate_execution_file_contract_without_mutating_original(role):
    from sagents.v2.optimization.principles import RECORD_FORMAT_GUIDE
    runner = Runner()
    engine = optimizer(runner)
    configured = getattr(engine, role)
    before = configured.model_dump_json()
    if role == 'test_designer':
        from sagents.v2.optimization.generator import AgentPackageTestGenerator
        configured = AgentPackageTestGenerator(runner=runner, designer=configured).designer
        assert engine.test_designer.model_dump_json() == before
    instructions = configured.package.resolved_manifest().agents[configured.agent_id].instructions.inline
    assert RECORD_FORMAT_GUIDE in instructions
    assert 'execution-001.json and assessment-001.json' in instructions
    assert 'comparison.json' in instructions
    assert 'No role may change tests, scorer or permissions' in instructions


def test_dialogue_driver_only_receives_user_visible_history_not_evaluation_files():
    from sagents.v2.optimization.principles import DIALOGUE_USER_PRINCIPLES, RECORD_FORMAT_GUIDE
    engine = optimizer(Runner())
    driver = engine.test_driver
    instructions = driver.package.resolved_manifest().agents[driver.agent_id].instructions.inline
    assert instructions == DIALOGUE_USER_PRINCIPLES
    assert RECORD_FORMAT_GUIDE not in instructions
    assert 'internal tool results, scores' in instructions
