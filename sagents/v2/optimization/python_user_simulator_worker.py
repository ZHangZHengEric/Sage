"""Private worker for imported reply(request) functions or UserSimulator instances."""
import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
from pathlib import Path
import sys

from sagents.v2.optimization.scorer_dependencies import DependencyCapture, ScorerDependencyError
from sagents.v2.optimization.scorer_runtime import _TEST_MODEL, _test_model
from sagents.v2.optimization.user_simulator import UserSimulator, UserSimulationRequest, UserSimulationReply


def invoke(module, request):
    simulator = getattr(module, 'USER_SIMULATOR', None)
    function = getattr(module, 'reply', None)
    if isinstance(simulator, UserSimulator) and function is None:
        result = simulator.reply(request)
    elif simulator is None and callable(function):
        result = function(request.model_dump(mode='json'))
    else:
        raise ValueError('export either reply(request) or USER_SIMULATOR = UserSimulator instance')
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if hasattr(result, 'model_dump'):
        result = result.model_dump(mode='json')
    return UserSimulationReply.model_validate(result, strict=True)


def main():
    path = Path(sys.argv[1]).resolve()
    from sagents.v2.optimization.scorer_dependencies import worker_request
    verified_request = worker_request()
    capture = DependencyCapture(path, bind_runtime='--bind-runtime' in sys.argv[2:])
    spec = importlib.util.spec_from_file_location('_sage_imported_user_simulator', path)
    module = importlib.util.module_from_spec(spec)
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        if '--validate' in sys.argv[2:]:
            tests = getattr(module, 'USER_SIMULATOR_TEST_CASES', None)
            if not isinstance(tests, (tuple, list)) or not 2 <= len(tests) <= 10:
                raise ValueError('USER_SIMULATOR_TEST_CASES must contain 2 to 10 contract tests')
            decisions = set()
            for test in tests:
                request = UserSimulationRequest.model_validate(test['request'])
                responses = test.get('model_responses')
                provider = _test_model(responses) if responses is not None else None
                token = _TEST_MODEL.set(provider)
                try:
                    result = invoke(module, request)
                    if provider is not None and len(provider.requests) != len(responses):
                        raise ValueError('unused recorded model_responses in user simulator contract test')
                finally:
                    _TEST_MODEL.reset(token)
                expected = UserSimulationReply.model_validate(test['expected_reply'], strict=True)
                if result != expected:
                    raise ValueError('user simulator contract test did not match expected_reply')
                decisions.add(result.can_continue)
            if decisions != {True, False}:
                raise ValueError('user simulator contract tests must exercise both continue and stop')
            contract = getattr(module, 'USER_SIMULATOR_CONTRACT', None)
            if contract is not None and (not isinstance(contract, str) or not contract.strip() or len(contract) > 16000):
                raise ValueError('USER_SIMULATOR_CONTRACT must be nonempty text up to 16000 characters')
            output = {'status': 'passed', 'protocol': 'sage.rsi.user-simulator/v1', 'cases': len(tests)}
            if contract is not None:
                output['user_simulator_contract'] = contract
        else:
            request = (UserSimulationRequest.model_validate(verified_request) if verified_request is not None
                else UserSimulationRequest.model_validate_json(sys.stdin.buffer.readline(32 * 1024 * 1024 + 1)))
            output = invoke(module, request).model_dump(mode='json')
    dependencies = capture.finish(module, declaration='USER_SIMULATOR_DEPENDENCIES')
    sys.stdout.write(json.dumps({'payload': output, 'dependency_manifest': dependencies}))
    sys.stdout.flush()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from sagents.v2.contracts.errors import SageV2Error
        if '--validate' in sys.argv[2:]:
            result = {'status': 'failed', 'error': f'{type(error).__name__}: {error}'[:1000]}
        else:
            failure = ({'code': 'scorer.dependencies_changed', 'retryable': False}
                if isinstance(error, ScorerDependencyError) else
                {'code': error.info.code, 'retryable': error.info.retryable} if isinstance(error, SageV2Error) else
                {'code': 'user_simulator.execution_failed', 'retryable': False, 'error_type': type(error).__name__})
            result = {'execution_error': failure}
        sys.stdout.write(json.dumps(result))
        sys.stdout.flush()
