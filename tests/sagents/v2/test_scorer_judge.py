"""Imported scorers own all model scoring; RSI supplies no judge callback."""
import pytest
from sagents.v2.optimization.python_scorer import ScorerExecutionError
from tests.sagents.v2.test_python_scorer import scorer, request

@pytest.mark.asyncio
async def test_imported_scorer_cannot_request_a_framework_judge(tmp_path):
    module = scorer(tmp_path, "def score(request, host): return host.judge(messages=[])\n")
    with pytest.raises(ScorerExecutionError):
        await module.score(request())

@pytest.mark.asyncio
async def test_imported_scorer_can_own_its_scoring_implementation(tmp_path):
    module = scorer(tmp_path, "def score(request): return {'score': .75, 'passed': False, 'rationale': 'Scorer-owned result'}\n")
    assert (await module.score(request())).grade.score == .75
