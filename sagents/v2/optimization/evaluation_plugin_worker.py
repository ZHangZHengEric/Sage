"""Isolated capability validation and execution; no Eval Agent policy."""
import asyncio
from contextlib import redirect_stdout
import importlib.util
import inspect
import json
from pathlib import Path
import sys

from sagents.v2.optimization.comparison_plugin import ComparisonPreparationRequest, PreparedComparisonArtifact
from sagents.v2.optimization.contracts import OptimizationDiagnosis, OptimizationDiagnosisSummary
from sagents.v2.optimization.evaluation_plugin import (
    AnalysisRequest, EvaluationCapabilities, EvaluationRequest, EvaluationResult, SummaryRequest,
)
from sagents.v2.optimization.scorer_dependencies import DependencyCapture, worker_request

OPERATIONS = {'prepare': (ComparisonPreparationRequest, PreparedComparisonArtifact),
    'evaluate': (EvaluationRequest, EvaluationResult), 'analyze': (AnalysisRequest, OptimizationDiagnosis),
    'summarize': (SummaryRequest, OptimizationDiagnosisSummary)}


def invoke(module, capabilities, operation, value):
    if operation not in OPERATIONS or not getattr(capabilities, operation):
        raise ValueError('Evaluation operation was not declared')
    request_type, result_type = OPERATIONS[operation]
    request = request_type.model_validate(value)
    result = getattr(module, operation)(request.model_dump(mode='json'))
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    result = result_type.model_validate(result.model_dump(mode='json') if hasattr(result, 'model_dump') else result)
    if operation == 'evaluate':
        if (capabilities.mode == 'pairwise') != (result.comparison is not None):
            raise ValueError('Evaluation mode differs from declared capability')
        if capabilities.evaluation_includes_analysis and not (result.analysis
                or result.grade and result.grade.diagnosis or result.comparison and result.comparison.analysis):
            raise ValueError('Evaluation promised analysis but omitted it')
    return result


def main():
    path = Path(sys.argv[1]).resolve()
    verified = worker_request()
    capture = DependencyCapture(path, bind_runtime='--bind-runtime' in sys.argv[2:], capture_reads=False)
    spec = importlib.util.spec_from_file_location('_sage_evaluation_plugin', path)
    module = importlib.util.module_from_spec(spec)
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        capabilities = EvaluationCapabilities.model_validate(module.EVALUATION_CAPABILITIES)
        declared = {name for name in OPERATIONS if getattr(capabilities, name)}
        if not declared:
            raise ValueError('Declare at least one plugin capability')
        for name in declared:
            function = getattr(module, name, None)
            if not callable(function):
                raise ValueError(f'Missing declared function: {name}')
            inspect.signature(function).bind({})
        if '--validate' in sys.argv[2:]:
            contract = module.EVALUATION_CONTRACT
            if not isinstance(contract, str) or not contract.strip() or len(contract) > 16000:
                raise ValueError('EVALUATION_CONTRACT must contain 1 to 16000 characters')
            tests = module.EVALUATION_TEST_CASES
            if not isinstance(tests, (list, tuple)) or not 1 <= len(tests) <= 10:
                raise ValueError('EVALUATION_TEST_CASES requires 1 to 10 cases')
            tested = set()
            for test in tests:
                from sagents.v2.optimization.scorer_runtime import _TEST_MODEL, _test_model
                responses = test.get('model_responses')
                provider = _test_model(responses) if responses is not None else None
                token = _TEST_MODEL.set(provider)
                try:
                    result = invoke(module, capabilities, test['operation'], test['request']).model_dump(mode='json')
                    if any(result.get(key) != value for key, value in test['expected'].items()):
                        raise ValueError('Evaluation self-test result differs')
                    if provider is not None and len(provider.requests) != len(responses):
                        raise ValueError('Unused self-test model responses')
                finally:
                    _TEST_MODEL.reset(token)
                tested.add(test['operation'])
            if tested != declared:
                raise ValueError('Self-tests must cover every declared capability')
            output = {'status': 'passed', 'cases': len(tests),
                'protocol': 'sage.rsi.comparison/v1' if capabilities.mode == 'pairwise' else 'sage.rsi.scorer/v1',
                'evaluation_protocol': 'sage.rsi.evaluation/v1',
                'capabilities': capabilities.model_dump(mode='json'), 'scoring_contract': contract}
        else:
            envelope = verified if verified is not None else json.loads(sys.stdin.buffer.readline(32 * 1024 * 1024 + 1))
            output = invoke(module, capabilities, envelope['operation'], envelope['request']).model_dump(mode='json')
    manifest = capture.finish(module, declaration='EVALUATION_DEPENDENCIES')
    sys.stdout.write(json.dumps({'payload': output, 'dependency_manifest': manifest}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if '--validate' not in sys.argv[2:]:
            from sagents.v2.contracts.errors import SageV2Error
            # Preserve only typed model failure identity, never provider messages
            # or credentials. The host may resume known transient model failures.
            from sagents.v2.optimization.scorer_dependencies import ScorerDependencyError
            failure = ({'code': 'scorer.dependencies_changed', 'retryable': False}
                if isinstance(error, ScorerDependencyError) else
                {'code': error.info.code, 'retryable': error.info.retryable}
                if isinstance(error, SageV2Error) else
                {'code': 'scorer.execution_failed', 'retryable': False, 'error_type': type(error).__name__})
            sys.stdout.write(json.dumps({'execution_error': failure}))
            sys.stdout.flush()
            sys.exit(0)
        sys.stdout.write(json.dumps({'status': 'failed', 'error': f'{type(error).__name__}: {error}'[:1000]}))

