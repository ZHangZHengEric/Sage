"""Private worker for dataset-owned comparison plugins; no rendering in Sage."""
import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
from pathlib import Path
import sys

from sagents.v2.optimization.comparison_plugin import (
    ComparisonPreparationRequest, ComparisonRequest, PreparedComparisonArtifact,
)
from sagents.v2.optimization.pairwise import PairwiseDecision
from sagents.v2.optimization.scorer_dependencies import DependencyCapture, worker_request


def invoke(module, operation, value):
    if operation not in {'prepare', 'compare'}:
        raise ValueError('unsupported comparison operation')
    request_type, result_type = ((ComparisonPreparationRequest, PreparedComparisonArtifact)
        if operation == 'prepare' else (ComparisonRequest, PairwiseDecision))
    request = request_type.model_validate(value)
    result = getattr(module, operation)(request.model_dump(mode='json'))
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if hasattr(result, 'model_dump'):
        result = result.model_dump(mode='json')
    return result_type.model_validate(result)


def main():
    path = Path(sys.argv[1]).resolve()
    verified = worker_request()
    # Runtime artifacts are separately bound by file manifests. Static non-code
    # dependencies must be declared; imported Python modules remain auto-bound.
    capture = DependencyCapture(path, bind_runtime='--bind-runtime' in sys.argv[2:], capture_reads=False)
    spec = importlib.util.spec_from_file_location('_sage_comparison_plugin', path)
    module = importlib.util.module_from_spec(spec)
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        if not all(callable(getattr(module, name, None)) for name in ('prepare', 'compare')):
            raise ValueError('comparison plugin must export prepare(request) and compare(request)')
        if '--validate' in sys.argv[2:]:
            tests = getattr(module, 'COMPARISON_TEST_CASES', None)
            if not isinstance(tests, (list, tuple)) or not 2 <= len(tests) <= 10:
                raise ValueError('COMPARISON_TEST_CASES requires 2 to 10 tests covering prepare and compare')
            operations = set()
            for test in tests:
                from sagents.v2.optimization.scorer_runtime import _TEST_MODEL, _test_model
                responses = test.get('model_responses')
                provider = _test_model(responses) if responses is not None else None
                token = _TEST_MODEL.set(provider)
                try:
                    result = invoke(module, test['operation'], test['request'])
                    if provider is not None and len(provider.requests) != len(responses):
                        raise ValueError('unused comparison self-test model responses')
                finally:
                    _TEST_MODEL.reset(token)
                if test['operation'] == 'compare':
                    if result.winner != test['expected_winner']:
                        raise ValueError('comparison self-test winner differs')
                elif result.artifact != test['expected_artifact']:
                    raise ValueError('preparation self-test artifact differs')
                operations.add(test['operation'])
            if operations != {'prepare', 'compare'}:
                raise ValueError('self-tests must cover both prepare and compare')
            contract = getattr(module, 'COMPARISON_CONTRACT', None)
            if not isinstance(contract, str) or not contract.strip() or len(contract) > 16000:
                raise ValueError('COMPARISON_CONTRACT must describe artifacts and preferences (1 to 16000 characters)')
            output = {'status': 'passed', 'cases': len(tests), 'protocol': 'sage.rsi.comparison/v1',
                'scoring_contract': contract}
        else:
            envelope = verified if verified is not None else json.loads(sys.stdin.buffer.readline(32 * 1024 * 1024 + 1))
            output = invoke(module, envelope['operation'], envelope['request']).model_dump(mode='json')
    manifest = capture.finish(module, declaration="COMPARISON_DEPENDENCIES")
    sys.stdout.write(json.dumps({'payload': output, 'dependency_manifest': manifest}))


if __name__ == '__main__':
    main()
