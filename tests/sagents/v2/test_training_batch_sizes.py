"""Training budgets govern cumulative suites without replaying historical rounds."""
import pytest

from sagents.v2.optimization.contracts import OptimizationCase, OptimizationSuite
from tests.sagents.v2.test_package_optimizer import AdaptiveRunner, bundle, context, optimizer


@pytest.mark.asyncio
async def test_generated_training_uses_independent_initial_and_increment_sizes():
    runner = AdaptiveRunner()
    result = await optimizer(runner).optimize(
        bundle(), context=context(), goal="Conversions", rounds=2,
        validation_case_count=1, initial_training_case_count=3,
        training_cases_per_round=2,
    )
    assert [d['case_count'] for split, d in runner.designs if split == 'training'] == [3, 2, 2]
    assert [len(a.cases) for a in result.report.training_additions] == [3, 2, 2]
    assert sum(c.split == 'training' for c in result.report.suite.cases) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize('pool_size,increment,expected,generated', [(8, 2, 6, []), (3, 2, 6, [1, 2]), (8, 0, 2, [])])
async def test_imported_pool_is_consumed_in_order_before_designer(pool_size, increment, expected, generated):
    runner = AdaptiveRunner()
    pool = [OptimizationCase(id=f'pool-{i}', input=f'Conversion {i}', rubric='Correct conversion') for i in range(pool_size)]
    dev = OptimizationCase(id='dev', input='Independent conversion', rubric='Correct conversion', split='validation')
    result = await optimizer(runner).optimize(
        bundle(), context=context(), goal="Conversions", rounds=2,
        suite=OptimizationSuite(cases=(*pool, dev)), validation_case_count=1,
        initial_training_case_count=2, training_cases_per_round=increment,
    )
    training = [c for c in result.report.suite.cases if c.split == 'training']
    assert len(training) == expected
    assert [c.id for c in training[:min(pool_size, expected)]] == [c.id for c in pool[:expected]]
    assert [d['case_count'] for split, d in runner.designs if split == 'training'] == generated
    assert [c.case.id for c in result.report.baseline.cases if c.case.split == 'training'] == ['pool-0', 'pool-1']
