"""Scorer code/data bindings are validated without live model access."""
import json

import pytest

from sagents.v2.optimization.python_scorer import ScorerExecutionError
from tests.sagents.v2.test_python_scorer import scorer, request


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['helper', 'data', 'new_file'])
async def test_declared_code_and_data_cannot_change_after_validation(tmp_path, mutation):
    resources = tmp_path / 'resources'
    resources.mkdir()
    data = resources / 'answers.json'
    data.write_text('{"answer": "42"}')
    helper = tmp_path / 'helper.py'
    helper.write_text('ANSWER = "42"\n')
    source = f'''import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('fixture_helper', {str(helper)!r})
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
SCORER_DEPENDENCIES = [{str(resources)!r}, {str(helper)!r}]
def score(request):
    import json
    answer = json.loads(Path({str(data)!r}).read_text())['answer']
    correct = request['observation']['output'] == answer == helper.ANSWER
    return {{'score': int(correct), 'passed': correct, 'rationale': 'Compared'}}
SCORER_TEST_CASES = ''' + repr([{'request': request().model_dump(mode='json'),
        'expected_score': 1, 'expected_passed': True}])
    module = scorer(tmp_path, source)
    validation = await module.validate()
    assert validation['dependency_file_count'] >= 2
    assert (await module.score(request())).grade.score == 1
    if mutation == 'helper':
        helper.write_text('ANSWER = "99"\n')
    elif mutation == 'data':
        data.write_text('{"answer": "99"}')
    else:
        (resources / 'new_rule.py').write_text('RULE = "new"')
    with pytest.raises(ScorerExecutionError, match='frozen scorer dependencies changed'):
        await module.score(request())
    # Re-admission produces a different dependency version even with identical entry source.
    if mutation == 'new_file':
        reimported = scorer(tmp_path, source)
        assert (await reimported.validate())['dependency_binding'] != validation['dependency_binding']


@pytest.mark.asyncio
async def test_undeclared_lazy_data_cannot_silently_enter_an_admitted_scorer(tmp_path):
    lazy = tmp_path / 'lazy.txt'
    lazy.write_text('secret')
    module = scorer(tmp_path, f'''from pathlib import Path
def score(request):
    if request['case']['id'] == 'lazy':
        Path({str(lazy)!r}).read_text()
    return {{'score': 1, 'passed': True, 'rationale': 'Compared'}}
SCORER_TEST_CASES = ''' + repr([{'request': request().model_dump(mode='json'),
        'expected_score': 1, 'expected_passed': True}]))
    await module.validate()
    req = request().model_copy(update={'case': request().case.model_copy(update={'id': 'lazy'})})
    with pytest.raises(ScorerExecutionError, match='frozen scorer dependencies changed'):
        await module.score(req)
    assert str(tmp_path) not in json.dumps((await module.validate()))


@pytest.mark.asyncio
async def test_source_modified_during_execution_is_rejected(tmp_path):
    module = scorer(tmp_path, '''from pathlib import Path
def score(request):
    Path(__file__).write_text('# changed during execution')
    return {'score': 1, 'passed': True, 'rationale': 'Compared'}
''')
    with pytest.raises(ScorerExecutionError, match='frozen scorer source changed'):
        await module.score(request())
