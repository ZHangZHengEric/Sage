"""File mode does not treat chat output as an evaluation or grant new tools."""
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationAgent, OptimizationObservation
from sagents.v2.optimization.evaluation_files import (
    CONTROL, collect_evaluation_output, evaluation_file_call, evaluation_response,
)
from tests.sagents.v2.test_package_optimizer import bundle


def evaluator():
    package = bundle('evaluator')
    definition = package.manifest.agents['assistant'].model_copy(update={'tools': ('file_read', 'file_write')})
    return OptimizationAgent(package=package.model_copy(update={'manifest': package.manifest.model_copy(
        update={'agents': {'assistant': definition}})}), agent_id='assistant')


def test_evaluation_file_is_isolated_and_input_hash_binds_recovery(tmp_path):
    original = evaluator()
    data = {'execution': [{'user': 'untrusted conversation marker', 'tool_result': 'actual result'}]}
    prepared, header = evaluation_file_call(original, 'Diagnose', data, {}, directory=tmp_path)
    assert 'untrusted conversation marker' not in json.dumps(header)
    assert json.loads(prepared.package.files['evaluation/inputs/conversation.json']) == data['execution']
    assert CONTROL not in original.package.files
    assert (tmp_path / header['sha256'] / 'conversation.json').exists()
    assert header['sha256'] != evaluation_file_call(original, 'Diagnose', {'execution': []}, {})[1]['sha256']
    assert set(prepared.package.manifest.agents['assistant'].tools) == {'file_read', 'file_write'}


def test_chat_reply_never_substitutes_for_the_assessment_file(tmp_path):
    prepared, _ = evaluation_file_call(evaluator(), 'Diagnose', {}, {})
    observation = OptimizationObservation(state='completed', output='{"summary":"This is only a chat reply"}')
    with pytest.raises(ValueError, match='assessment.json'):
        evaluation_response(observation, True)
    (tmp_path / 'evaluation').mkdir()
    path = tmp_path / 'evaluation' / 'assessment.json'
    path.write_text('{"summary":"Actual file"}')
    evidence = collect_evaluation_output(tmp_path, prepared.package)
    assert evaluation_response(observation.model_copy(update={'evidence': evidence}), True) == path.read_text()
    path.unlink()
    path.symlink_to(tmp_path / 'private-file')
    assert 'evaluation_record_error' in collect_evaluation_output(tmp_path, prepared.package)


def test_sdk_without_file_tools_keeps_its_existing_contract():
    original = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    assert evaluation_file_call(original, 'Diagnose', {'original': True}, {}) == (original, {'original': True})


@pytest.mark.asyncio
async def test_file_backed_diagnosis_keeps_the_whole_execution_in_one_assessment():
    from sagents.v2.optimization.contracts import OptimizationGrade
    from sagents.v2.optimization.diagnostics import diagnose_scored_execution
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis
    entries = [{'tool_result': 'x' * 90000}, {'user': 'last important confirmation'}]
    calls = []
    async def invoke(request):
        calls.append(request)
        return json.dumps(diagnosis(1))
    grade = OptimizationGrade(score=.5, passed=False, rationale='Fixed scorer')
    result = await diagnose_scored_execution(grade=grade, entries=entries, rubric='Complete',
        policy='Actual version', invoke=invoke, file_backed=True)
    assert len(calls) == 1
    assert [part['record'] for part in calls[0]['data']['execution']] == entries
    assert result.score == .5 and not result.passed


def test_paged_long_strings_are_lossless_and_each_read_stays_small():
    from sagents.v2.optimization.evaluation_files import pageable_evidence, read_ranges
    original = 'long quote " and slash \\ and newline\n' * 5000
    view = pageable_evidence({'actual_result': original})
    assert ''.join(view['actual_result']['text_parts']) == original
    text = json.dumps(view, ensure_ascii=False, indent=2)
    lines = text.splitlines()
    ranges = read_ranges(text)
    assert ranges[0][0] == 1 and ranges[-1][1] == len(lines)
    for i, (first, last) in enumerate(ranges):
        assert len(json.dumps('\n'.join(lines[first - 1:last]), ensure_ascii=False)) < 8500
        if i:
            assert first == ranges[i - 1][1] + 1


def test_framework_rejects_an_assessment_without_complete_read_coverage(tmp_path):
    prepared, _ = evaluation_file_call(evaluator(), 'Diagnose', {'input': 'actual context'}, {})
    (tmp_path / 'evaluation').mkdir()
    (tmp_path / 'evaluation' / 'assessment.json').write_text('{"summary":"Unsupported claim"}')
    observation = OptimizationObservation(state='completed', output='Saved', evidence={'final_items': []})
    outcome = collect_evaluation_output(tmp_path, prepared.package, observation)
    assert outcome['evaluation_read_coverage'][0]['read_through_line'] == 0
    assert 'Read all evidence' in outcome['evaluation_record_error']


def test_internal_grades_require_diagnosis_and_validate_message_indexes():
    from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationDiagnosis
    from sagents.v2.optimization.evaluation_files import validate_assessment_evidence
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis
    grade = OptimizationGrade(score=.5, passed=False, rationale='Partial completion')
    source = {'case': {'input': 'Question'}, 'observation':
        OptimizationObservation(state='completed', output='Reply').model_dump(mode='json')}
    with pytest.raises(ValueError, match='score alone'):
        validate_assessment_evidence(grade, source, file_mode=True)
    # File mode exposes two simple messages, not a larger runtime envelope.
    for index in (-1, 2, 999):
        invalid = grade.model_copy(update={'diagnosis': OptimizationDiagnosis.model_validate(diagnosis(index))})
        with pytest.raises(ValueError, match='outside'):
            validate_assessment_evidence(invalid, source, file_mode=True)
    valid = grade.model_copy(update={'diagnosis': OptimizationDiagnosis.model_validate(diagnosis(1))})
    validate_assessment_evidence(valid, {'original_data': source}, file_mode=True)
    assert valid.score == grade.score and valid.passed == grade.passed


def test_evaluation_receives_only_enabled_capability_files_and_keeps_them_separate():
    from sagents.v2.agent.management import AgentPackageBundle
    from sagents.v2.optimization.diagnostics import execution_configuration
    from sagents.v2.tool.generated import GeneratedTool
    data = bundle().model_dump(mode='json')
    data['manifest']['agents']['assistant']['skills'] = ['units', 'external']
    data['manifest']['agents']['assistant']['tools'] = ['rsi_identity']
    tool = GeneratedTool(description='Return the supplied value',
        input_schema={'type': 'object', 'properties': {'value': {'type': 'number'}}, 'required': ['value']},
        expression={'var': 'value'})
    data['files'].update({'tools/rsi/rsi_identity.json': tool.model_dump_json(),
        'skills/unused/SKILL.md': 'UNUSED PRIVATE CONTENT', 'private.env': 'UNRELATED PRIVATE CONTENT'})
    target = AgentPackageBundle.model_validate(data)
    configuration = execution_configuration(target, 'assistant')
    assert configuration['package_hash'] == target.content_hash
    assert configuration['skills'] == [{'name': 'units', 'bundled': True}, {'name': 'external', 'bundled': False}]
    assert {r['source'] for r in configuration['resources']} == {'skills/units/SKILL.md', 'tools/rsi/rsi_identity.json'}
    assert 'PRIVATE CONTENT' not in json.dumps(configuration)
    prepared, header = evaluation_file_call(evaluator(), 'Diagnose', {'agent_configuration': configuration}, {})
    assert prepared.package.files['evaluation/inputs/configuration-001.md'] == 'Check units.'
    assert prepared.package.files['evaluation/inputs/configuration-002.md'] == tool.model_dump_json()
    context = json.loads(prepared.package.files['evaluation/inputs/context.json'])
    assert all('content' not in resource for resource in context['agent_configuration']['resources'])
    assert context['agent_configuration']['resources'][0]['file'] == 'inputs/configuration-001.md'
    assert 'Check units.' not in json.dumps(header)


def test_scorer_details_are_separate_readable_evidence_not_chat_payload():
    details = {'component_checks': [{'passed': False, 'reason': 'Missing final summary'}]}
    original = {'score': 0, 'passed': False, 'rationale': 'Fixed', 'scorer_details': details}
    prepared, header = evaluation_file_call(evaluator(), 'Diagnose', {
        'execution': [{'role': 'assistant', 'content': 'Recorded answer'}],
        'authoritative_grade': original}, {})
    files = prepared.package.files
    assert json.loads(files['evaluation/inputs/scorer.json']) == details
    context = json.loads(files['evaluation/inputs/context.json'])
    assert context['authoritative_grade']['scorer_details_file'] == 'inputs/scorer.json'
    assert 'scorer_details' not in context['authoritative_grade']
    assert any(f['path'] == 'inputs/scorer.json' for f in header['files'])
    assert 'Missing final summary' not in json.dumps(header)
    assert original['scorer_details'] == details


@pytest.mark.parametrize('state,kind,code,expected', [
    ('suspended', 'user_input', 'loop.repeated_pattern', True),
    ('suspended', 'approval', 'loop.repeated_pattern', False),
    ('suspended', 'user_input', 'permission.required', False),
    ('completed', 'user_input', 'loop.repeated_pattern', False),
])
def test_only_explicit_user_loop_suspension_is_a_repairable_assessment(state, kind, code, expected):
    from sagents.v2.optimization.evaluation_files import assessment_loop_interrupted
    observation = OptimizationObservation(state=state, evidence={'runtime_events': [
        {'type': 'interaction.requested', 'data': {'interaction_type': kind, 'payload': {'reason_code': code}}}]})
    assert assessment_loop_interrupted(observation) is expected


def test_persisted_file_validation_keeps_native_pause_and_completion_basis(tmp_path):
    from sagents.v2.optimization.evaluation_files import persist_assessment
    observation = OptimizationObservation(state='suspended', evidence={
        'evaluation_record': '{}', 'evaluation_read_coverage': [{'file': 'inputs/context.json',
            'read_through_line': 4, 'total_lines': 4}]})
    persist_assessment(tmp_path, {'protocol': 'sage.rsi.evaluation-files/v1', 'sha256': 'inputs-hash'}, observation)
    record = json.loads((tmp_path/'inputs-hash/validation.json').read_text())
    assert record['valid'] is True
    assert record['native_state'] == 'suspended'
    assert record['completion_basis'] == 'validated_assessment_file'
    assert record['read_coverage'][0]['read_through_line'] == 4


@pytest.mark.parametrize('code,record,error,coverage,expected', [
    ('model.empty_semantic_response', '{}', None, True, True),
    ('model.provider_transient', '{}', None, True, False),
    ('model.empty_semantic_response', '', None, True, True),
    ('model.empty_semantic_response', '{}', 'Missing evidence', True, True),
    ('model.empty_semantic_response', '{}', None, False, True),
])
def test_only_exact_empty_terminal_reply_can_defer_to_assessment_validation(code, record, error, coverage, expected):
    from sagents.v2.optimization.evaluation_files import assessment_terminal_response_empty
    observation = OptimizationObservation(state='suspended', evidence={
        'error': {'code': code, 'retryable': True, 'category': 'provider_transient'},
        'evaluation_record': record, 'evaluation_record_error': error,
        'evaluation_read_coverage': [{'read_through_line': 4 if coverage else 0, 'total_lines': 4}]})
    assert assessment_terminal_response_empty(observation) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize('needs_read_repair', [False, True])
async def test_empty_reply_after_written_assessment_does_not_restart_successful_analysis(tmp_path, needs_read_repair):
    from sagents.v2.optimization.contracts import OptimizationGrade
    from tests.sagents.v2.test_package_optimizer import Runner, optimizer, context, suite
    calls = []
    class FileRunner(Runner):
        async def run(self, package, agent_id, content, ctx):
            if CONTROL not in package.files:
                return await super().run(package, agent_id, content, ctx)
            request = json.loads(content)
            calls.append(request['response_schema']['title'])
            context_doc = json.loads(package.files['evaluation/inputs/context.json'])
            incomplete = needs_read_repair and 'repair' not in context_doc
            if 'repair' in context_doc:
                assert 'Read all evidence' in context_doc['repair']['reason']
            assessment = {'summary': 'Official score confirms success', 'findings': [],
                'strengths': ['Task completed'], 'uncertainties': [], 'coverage': 'All supplied messages',
                'next_action': 'no_change', 'next_verification': 'No justified edit'}
            return OptimizationObservation(state='suspended', evidence={
                'error': {'code': 'model.empty_semantic_response', 'retryable': True, 'category': 'provider_transient'},
                'evaluation_record': json.dumps(assessment),
                'evaluation_record_error': 'Read all evidence files; missing lines 3-4' if incomplete else None,
                'evaluation_read_coverage': [{'read_through_line': 2 if incomplete else 4, 'total_lines': 4}]})
    opt = optimizer(FileRunner())
    opt.evaluator = evaluator()
    async def score(case, observation):
        return OptimizationGrade(score=1, passed=True, rationale='Official scorer')
    await opt.optimize(bundle(), context=context(), goal='Complete', suite=suite(), rounds=1,
        validation_case_count=1, grow_training=False, final_max_cases=0, authoritative_grader=score,
        call_retries=1, restart_file_evaluator=True, recovery_binding_id='frozen-test-binding',
        journal_path=tmp_path/'audit.jsonl')
    assert calls and set(calls) == {'OptimizationDiagnosis'}
    events = [json.loads(line) for line in (tmp_path/'audit.jsonl').read_text().splitlines()]
    assert not any(e['event'] in {'call_retry_scheduled', 'agent_call_failed'} for e in events)
    validations = list((tmp_path/'evaluations').rglob('validation.json'))
    assert len(calls) == (2 if needs_read_repair else 1) * sum(e['event'] == 'execution_scored' for e in events)
    assert any(json.loads(p.read_text())['valid'] for p in validations)
    assert len(validations) == (4 if needs_read_repair else 2)  # Train/dev; stability reuses the same input documents.
    assert all(json.loads(p.read_text())['native_state'] == 'suspended' for p in validations)


@pytest.mark.asyncio
@pytest.mark.parametrize('granted,code,valid,succeeds', [
    (True, 'model.empty_semantic_response', True, True),
    (False, 'model.empty_semantic_response', True, False),
    (True, 'model.provider_transient', True, False),
    (True, 'model.empty_semantic_response', False, False),
    (True, 'model.empty_semantic_response', 'repair', True),
    (True, 'model.empty_semantic_response', 'missing', False),
])
async def test_independent_test_analysis_uses_the_same_file_completion_boundary(tmp_path, granted, code, valid, succeeds):
    from sagents.v2.optimization.observer import IsolatedTestEvaluator, HumanTestExecutionFailure
    from sagents.v2.optimization.contracts import OptimizationDiagnosis
    from tests.sagents.v2.test_package_optimizer import context
    calls = []
    class FileRunner:
        async def run(self, package, agent_id, content, ctx):
            calls.append(content)
            incomplete = valid == 'repair' and len(calls) == 1
            if valid == 'repair' and len(calls) > 1:
                doc = json.loads(package.files['evaluation/inputs/context.json'])
                assert 'missing lines' in doc['repair']['reason']
            record = {'summary': 'Recorded success', 'findings': [], 'strengths': ['Completed'],
                'uncertainties': [], 'coverage': 'All evidence', 'next_action': 'no_change'} if valid else {'findings': 'invalid'}
            return OptimizationObservation(state='suspended', evidence={
                'error': {'code': code, 'retryable': True, 'category': 'provider_transient'},
                'evaluation_record': None if valid == 'missing' else json.dumps(record),
                'evaluation_record_error': 'Read all evidence; missing lines 3-4' if incomplete else None,
                'evaluation_read_coverage': [{'read_through_line': 2 if incomplete else 4, 'total_lines': 4}]})
    role = evaluator()
    measure = IsolatedTestEvaluator(runner=FileRunner(), evaluator=role, driver=role,
        context=context(), goal='Complete', retry_local_evaluations=granted,
        max_transport_retries=0, evidence_directory=tmp_path)
    if succeeds:
        result = await measure._ask(measure.evaluator, 'Diagnose', {}, OptimizationDiagnosis)
        assert result.summary == 'Recorded success'
        assert len(calls) == (2 if valid == 'repair' else 1)
        validations = list(tmp_path.rglob('validation.json'))
        assert any(json.loads(p.read_text())['valid'] for p in validations)
        assert all(json.loads(p.read_text())['native_state'] == 'suspended' for p in validations)
    else:
        with pytest.raises((HumanTestExecutionFailure, ValueError)):
            await measure._ask(measure.evaluator, 'Diagnose', {}, OptimizationDiagnosis)
        assert not any(json.loads(p.read_text())['valid'] for p in tmp_path.rglob('validation.json'))
