"""Data validity is deterministic; model review is a source-aware opinion."""
import json

import pytest
from pydantic import ValidationError

from sagents.v2.optimization.contracts import OptimizationObservation, OptimizationPatch
from sagents.v2.optimization.dataset import OptimizationDataset, validate_imported_dataset
from sagents.v2.optimization.dataset_versions import (
    DatasetVersion, DatasetRevisionRequest, SuitePreflightPolicy,
)
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


def dataset():
    cases = list(suite().cases)
    cases.append(cases[1].model_copy(update={'id': 'second-dev'}))
    cases.append(cases[0].model_copy(update={'id': 'human-test', 'split': 'test'}))
    return OptimizationDataset(name='Fixed benchmark', cases=tuple(cases))


def revision(version, case_id='second-dev'):
    return DatasetRevisionRequest(expected_version=version.id, confirmed=True, exclusions=[{
        'case_id': case_id, 'reason_code': 'missing_information',
        'reason': 'Required fixture input is absent', 'evidence': ['Original fixture has no required field'],
    }])


def test_human_revision_preserves_original_and_records_denominators_and_provenance():
    original = DatasetVersion.imported(dataset())
    revised = original.revise(revision(original), operator='human-alice')
    assert original.dataset == revised.dataset
    assert len(original.active_dataset().cases) == 4
    assert len(revised.active_dataset().cases) == 3
    assert original.id != revised.id and revised.parent_version == original.id
    mark = revised.exclusions[0]
    assert mark.operator == 'human-alice' and mark.source_version == original.id
    assert mark.confirmed_at and mark.evidence
    assert revised.manifest()['label'] == 'revised'
    assert revised.manifest()['counts']['validation'] == dict(original=2, excluded=1, active=1)
    assert revised.manifest()['counts']['test']['original'] == 1
    next_version = revised.revise(revision(revised, 'human-test'), operator='human-bob')
    assert next_version.parent_version == revised.id
    assert next_version.source_version == original.id
    assert len(next_version.exclusions) == 2 and len(revised.exclusions) == 1
    assert DatasetVersion.model_validate_json(revised.model_dump_json()) == revised
    with pytest.raises(ValueError, match='version changed'):
        original.revise(revision(revised), operator='alice')
    with pytest.raises(ValueError, match='already excluded'):
        revised.revise(revision(revised), operator='alice')
    tampered = revised.model_dump(mode='json')
    tampered['exclusions'][0]['reason'] = 'changed'
    with pytest.raises(ValidationError, match='identity mismatch'):
        DatasetVersion.model_validate(tampered)


def test_excluding_test_never_claims_the_complete_source_denominator():
    original = DatasetVersion.imported(dataset())
    revised = original.revise(revision(original, 'human-test'), operator='alice')
    assert revised.manifest()['counts']['test'] == dict(original=1, excluded=1, active=0)
    assert revised.manifest()['complete_original_test'] is False
    assert revised.manifest()['label'] == 'revised'


def test_exclusion_requires_confirmation_and_defect_evidence_not_low_score():
    version = DatasetVersion.imported(dataset())
    value = revision(version).model_dump(mode='json')
    for patch in ({'confirmed': False}, {'confirmed': 1}, {'operator': 'model-tuner'}):
        with pytest.raises(ValidationError):
            DatasetRevisionRequest.model_validate({**value, **patch})
    value['exclusions'][0]['reason_code'] = 'low_score'
    with pytest.raises(ValidationError):
        DatasetRevisionRequest.model_validate(value)
    with pytest.raises(ValidationError):
        OptimizationPatch.model_validate({'rationale': 'make scores better', 'exclude_cases': ['second-dev']})


def test_wire_protocol_fields_ids_and_splits_are_hard_errors():
    value = dataset().model_dump(mode='json')
    for name in ('format_version',):
        broken = {k: v for k, v in value.items() if k != name}
        with pytest.raises(ValueError, match=name):
            validate_imported_dataset(broken)
    for field in ('id', 'input', 'rubric', 'split'):
        broken = json.loads(json.dumps(value)); del broken['cases'][0][field]
        with pytest.raises(ValueError, match=field):
            validate_imported_dataset(broken)
    broken = json.loads(json.dumps(value)); broken['cases'][1]['id'] = broken['cases'][0]['id']
    with pytest.raises(ValueError, match='duplicate.*train'):
        validate_imported_dataset(broken)
    broken = json.loads(json.dumps(value)); broken['cases'][1]['split'] = 'mystery'
    with pytest.raises(ValidationError, match='split'):
        validate_imported_dataset(broken)


@pytest.mark.asyncio
@pytest.mark.parametrize('case_id', ['holdout-secret', 'invented-case'])
async def test_rejected_imported_semantic_opinion_is_recorded_without_changing_suite_or_leaking_dev(tmp_path, case_id):
    secret = 'PRIVATE-DEV-PREFLIGHT'
    class Reject(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.suite-reviewer':
                self.requests.append((package.manifest.metadata.id, content))
                return OptimizationObservation(state='completed', output=json.dumps({
                    'approved': False, 'rationale': secret, 'issues': [{
                        'kind': 'untestable', 'severity': 'blocking', 'case_ids': [case_id],
                        'rationale': secret, 'suggested_fix': 'Verify the scenario',
                        'evidence': ['A required fact may be absent'], 'impact': 'Authentication may be unavailable',
                    }]}))
            return await super().run(package, agent_id, content, ctx)
    runner = Reject(); journal = tmp_path / 'audit.jsonl'
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
        suite=suite(), validation_case_count=None, final_max_cases=0, rounds=1, journal_path=journal)
    assert result.report.suite_review.approved is False
    assert len(result.report.baseline.cases) == 2
    assert {case.id for case in result.report.suite.cases} == {'train', 'holdout-secret'}
    assert runner.target_hashes
    tuner = [content for name, content in runner.requests if name == 'test.tuner']
    assert tuner and all(secret not in content and 'holdout-secret' not in content for content in tuner)
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert any(e['event'] == 'suite_review_completed' and e['data']['disposition'] == 'diagnostic_only'
               and e['data']['review']['approved'] is False for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('repair_succeeds', [True, False])
async def test_generated_drafts_are_repaired_or_quarantined_before_admission(tmp_path, repair_succeeds):
    class Generated(Runner):
        repairs = 0
        async def run(self, package, agent_id, content, ctx):
            request = json.loads(content) if content.startswith('{') else {}
            task = request.get('task', '')
            if task.startswith('Design'):
                draft = suite().model_dump(mode='json')
                draft['cases'].insert(1, {**draft['cases'][0], 'id': 'broken-draft', 'input': 'Convert 3 km', 'rubric': 'BROKEN'})
                return OptimizationObservation(state='completed', output=json.dumps(draft))
            if task.startswith('Repair'):
                self.repairs += 1
                draft = request['data']['suite']
                if repair_succeeds:
                    for case in draft['cases']:
                        if case['rubric'] == 'BROKEN': case['rubric'] = 'Meters'
                return OptimizationObservation(state='completed', output=json.dumps(draft))
            if package.manifest.metadata.id == 'test.suite-reviewer':
                cases = request['data']['suite']['cases']
                issues = [{'kind': 'untestable', 'severity': 'blocking', 'case_ids': [case['id']],
                    'rationale': 'Invalid draft fixture', 'suggested_fix': 'Repair required field',
                    'evidence': ['BROKEN']} for case in cases if case['rubric'] == 'BROKEN']
                return OptimizationObservation(state='completed', output=json.dumps({
                    'approved': not issues, 'rationale': 'Draft review', 'issues': issues}))
            return await super().run(package, agent_id, content, ctx)
    runner = Generated(); journal = tmp_path / 'audit.jsonl'
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
        validation_case_count=None, final_max_cases=0, rounds=1, journal_path=journal,
        preflight_policy=SuitePreflightPolicy(generated_repairs=1))
    assert runner.repairs == 1
    ids = {case.id for case in result.report.suite.cases}
    assert ('broken-draft' in ids) == repair_succeeds
    assert len(result.report.baseline.cases) == (3 if repair_succeeds else 2)
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    if not repair_succeeds:
        assert any(e['event'] == 'generated_cases_quarantined' for e in events)
        assert all('BROKEN' not in json.dumps(e['data']) for e in events if e['event'] == 'suite_fixed')


def test_exclusions_cannot_remove_required_splits_or_forge_unknown_case_ids():
    original = DatasetVersion.imported(dataset())
    with pytest.raises(ValueError, match='training and validation'):
        original.revise(revision(original, 'train'), operator='alice')
    with pytest.raises(ValueError, match='unknown case IDs'):
        original.revise(revision(original, 'unknown'), operator='alice')
    assert original.manifest()['excluded_count'] == 0


@pytest.mark.asyncio
async def test_confirmed_training_fixture_is_absent_from_new_run_feedback_not_an_agent_defect():
    data = dataset()
    data = data.model_copy(update={'cases': (*data.cases,
        data.cases[0].model_copy(update={'id': 'legitimate-train', 'input': 'Convert 3 km'}))})
    original = DatasetVersion.imported(data)
    revised = original.revise(revision(original, 'train'), operator='alice')
    runner = Runner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
        suite=revised.active_dataset().optimization_suite(), validation_case_count=None, final_max_cases=0,
        rounds=1, dataset_manifest=revised.manifest())
    assert all(case.case.id != 'train' for case in result.report.baseline.cases)
    tuner = [json.loads(content) for name, content in runner.requests if name == 'test.tuner']
    assert tuner
    assert 'Required fixture input is absent' not in json.dumps(tuner)
    assert 'Original fixture has no required field' not in json.dumps(tuner)
    assert 'exclusions' not in result.report.dataset_manifest
    assert result.report.dataset_manifest['label'] == 'revised'
