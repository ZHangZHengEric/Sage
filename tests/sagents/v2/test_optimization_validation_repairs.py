import json

import pytest

from sagents.v2.optimization import OptimizationConstraints, OptimizationObservation
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


class RepairRunner(Runner):
    def __init__(self, *, stuck=False):
        super().__init__()
        self.stuck = stuck
        self.repairs = []
        self.target_prompts = []

    async def run(self, package, agent_id, content, ctx):
        if package.manifest.metadata.id == 'test.tuner':
            data = json.loads(content)['data']
            if 'validation_error' in data:
                self.repairs.append(data)
            prompt = 'x' * 101 if self.stuck or not self.repairs else 'Convert units accurately.'
            return OptimizationObservation(state='completed', output=json.dumps({'rationale': 'Repair limits', 'system_prompt': prompt}))
        if package.manifest.metadata.id == 'test.target':
            self.target_prompts.append(package.resolved_manifest().agents[agent_id].instructions.inline)
        return await super().run(package, agent_id, content, ctx)


@pytest.mark.asyncio
async def test_over_limit_proposal_is_repaired_in_same_round_before_inference():
    runner = RepairRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
        suite=suite(), validation_case_count=None, final_max_cases=0, rounds=1,
        constraints=OptimizationConstraints(max_system_prompt_chars=100), max_edit_repairs=2)
    assert len(runner.repairs) == 1
    feedback = runner.repairs[0]
    assert feedback['round'] == 1 and feedback['repair'] == 1
    assert '101 characters' in feedback['validation_error'] and '100' in feedback['validation_error']
    assert feedback['previous_proposal']['system_prompt'] == 'x' * 101
    assert 'x' * 101 not in runner.target_prompts
    assert len(result.report.rounds) == 1
    assert result.report.rounds[0].candidate_package is not None


@pytest.mark.asyncio
async def test_unfixable_draft_stops_at_repair_budget_without_executing_it():
    runner = RepairRunner(stuck=True)
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
        suite=suite(), validation_case_count=None, final_max_cases=0, rounds=1,
        constraints=OptimizationConstraints(max_system_prompt_chars=100), max_edit_repairs=2)
    assert len(runner.repairs) == 2
    assert result.report.rounds[0].candidate_package is None
    assert 'after 2 repairs' in result.report.rounds[0].reason
    assert 'x' * 101 not in runner.target_prompts


@pytest.mark.asyncio
async def test_file_editor_repairs_existing_round_draft_and_seals_only_valid_files(tmp_path):
    from sagents.v2.optimization.package_workspace import EDIT_CONTEXT, read_package
    class FileRepairRunner(RepairRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner':
                data = json.loads(content)['data']
                number = json.loads(package.files[EDIT_CONTEXT])['round']
                root = tmp_path / 'iterations' / f'round-{number:03d}'
                path = root / 'editor/package/files/prompts/base.md'
                if 'validation_error' in data:
                    self.repairs.append(data)
                    assert path.read_text() == 'x' * 101  # repair retains the actual failed draft
                    assert not (root / 'version').exists()
                    path.write_text('Convert units accurately.')
                else:
                    path.write_text('x' * 101)
                return OptimizationObservation(state='completed', output=json.dumps({'rationale': 'Fixed draft size'}))
            return await super().run(package, agent_id, content, ctx)
    runner = FileRepairRunner()
    engine = optimizer(runner)
    tuner_data = engine.tuner.package.model_dump(mode='json')
    tuner_data['manifest']['agents']['assistant']['tools'] = ['file_read', 'file_write', 'file_update']
    engine.tuner = engine.tuner.model_copy(update={'package': type(bundle()).model_validate(tuner_data)})
    result = await engine.optimize(bundle(), context=context(), goal='Conversions',
        suite=suite(), validation_case_count=None, final_max_cases=0, rounds=1,
        constraints=OptimizationConstraints(max_system_prompt_chars=100), max_edit_repairs=2,
        edit_package_files=True, tuner_workspace=tmp_path)
    assert len(runner.repairs) == 1
    candidate = result.report.rounds[0].candidate_package
    assert candidate is not None
    frozen = read_package(tmp_path / 'iterations/round-001/version/package')
    assert frozen == candidate
    assert frozen.files['prompts/base.md'] == 'Convert units accurately.'
