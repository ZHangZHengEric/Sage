"""Private subprocess entrypoint for imported Python score(request) modules."""
import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
from pathlib import Path
import sys

from sagents.v2.optimization.scoring import ScoringRequest, ScoringResult


def invoke(function, request):
    result = function(request.model_dump(mode='json'))
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if hasattr(result, 'model_dump'):
        result = result.model_dump(mode='json')
    if isinstance(result, dict) and 'grade' not in result and 'not_applicable_reason' not in result:
        result = {'grade': result}
    grade = result.get('grade') if isinstance(result, dict) else None
    if grade is not None and (not isinstance(grade, dict) or isinstance(grade.get('score'), bool)
            or not isinstance(grade.get('score'), (int, float))
            or not isinstance(grade.get('passed'), bool)
            or not isinstance(grade.get('rationale'), str) or not grade['rationale'].strip()):
        raise ValueError('grade requires numeric score, boolean passed and nonempty rationale')
    return ScoringResult.model_validate(result)


def main():
    path = Path(sys.argv[1]).resolve()
    validating = '--validate' in sys.argv[2:]
    spec = importlib.util.spec_from_file_location('_sage_imported_scorer', path)
    module = importlib.util.module_from_spec(spec)
    # Module diagnostics must not corrupt the JSON result channel.
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        function = getattr(module, 'score', None)
        if not callable(function):
            raise ValueError('Python scorer must export score(request)')
        inspect.signature(function).bind({})
        if validating:
            tests = getattr(module, 'SCORER_TEST_CASES', None)
            if not isinstance(tests, (list, tuple)) or not 1 <= len(tests) <= 10:
                raise ValueError('SCORER_TEST_CASES must contain 1 to 10 contract test cases')
            numeric_checks = 0
            for test in tests:
                request = ScoringRequest.model_validate(test['request'])
                from sagents.v2.optimization.scorer_runtime import _TEST_MODEL, _test_model
                responses = test.get('model_responses')
                provider = _test_model(responses) if responses is not None else None
                token = _TEST_MODEL.set(provider)
                try:
                    result = invoke(function, request)
                    if provider is not None and len(provider.requests) != len(responses):
                        raise ValueError('unused recorded model_responses in scorer self-test')
                finally:
                    _TEST_MODEL.reset(token)
                applicable = test.get('expected_applicable', True)
                if not isinstance(applicable, bool):
                    raise ValueError('expected_applicable must be boolean')
                if not applicable:
                    if result.grade is not None or any(key in test for key in ('expected_score', 'expected_passed')):
                        raise ValueError('non-applicable contract test must return an explicit reason without scores')
                    continue
                numeric_checks += 1
                expected_score, expected_passed = test['expected_score'], test['expected_passed']
                if (isinstance(expected_score, bool) or not isinstance(expected_score, (int, float))
                        or not 0 <= expected_score <= 1 or not isinstance(expected_passed, bool)):
                    raise ValueError('invalid expected score or pass state')
                if result.grade is None or abs(result.grade.score - expected_score) > 1e-9 or result.grade.passed != expected_passed:
                    raise ValueError('scorer contract test did not match expected score and pass state')
            if not numeric_checks:
                raise ValueError('at least one numeric scoring contract test is required')
            contract = getattr(module, 'SCORER_CONTRACT', None)
            if contract is not None and (not isinstance(contract, str) or not contract.strip() or len(contract) > 16000):
                raise ValueError('SCORER_CONTRACT must be a nonempty string up to 16000 characters')
            metadata = {'status': 'passed', 'cases': len(tests), 'protocol': 'sage.rsi.scorer/v1'}
            if contract is not None:
                metadata['scoring_contract'] = contract
            output = json.dumps(metadata)
        else:
            request = ScoringRequest.model_validate_json(sys.stdin.buffer.readline(32 * 1024 * 1024 + 1))
            output = invoke(function, request).wire_json()
    sys.stdout.write(output)
    sys.stdout.flush()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if '--validate' not in sys.argv[2:]:
            from sagents.v2.contracts.errors import SageV2Error
            # Preserve only typed model failure identity, never provider messages
            # or credentials. The host may resume known transient model failures.
            failure = ({'code': error.info.code, 'retryable': error.info.retryable}
                if isinstance(error, SageV2Error) else
                {'code': 'scorer.execution_failed', 'retryable': False, 'error_type': type(error).__name__})
            sys.stdout.write(json.dumps({'execution_error': failure}))
            sys.stdout.flush()
            sys.exit(0)
        sys.stdout.write(json.dumps({'status': 'failed', 'error': f'{type(error).__name__}: {error}'[:1000]}))

