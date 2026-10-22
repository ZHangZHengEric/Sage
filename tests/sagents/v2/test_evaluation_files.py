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
    assert json.loads(prepared.package.files['evaluation/inputs/record.json']) == data
    assert CONTROL not in original.package.files
    assert (tmp_path / header['sha256'] / 'record.json').exists()
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
        assert len(json.dumps('\n'.join(lines[first - 1:last]), ensure_ascii=False)) < 4500
        if i:
            assert first == ranges[i - 1][1] + 1


def test_framework_rejects_an_assessment_without_complete_read_coverage(tmp_path):
    prepared, _ = evaluation_file_call(evaluator(), 'Diagnose', {'input': 'actual context'}, {})
    (tmp_path / 'evaluation').mkdir()
    (tmp_path / 'evaluation' / 'assessment.json').write_text('{"summary":"Unsupported claim"}')
    observation = OptimizationObservation(state='completed', output='Saved', evidence={'final_items': []})
    outcome = collect_evaluation_output(tmp_path, prepared.package, observation)
    assert outcome['evaluation_read_coverage']['read_through_line'] == 0
    assert 'Read all evidence' in outcome['evaluation_record_error']
