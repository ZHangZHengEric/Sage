"""Host-bound frozen Python scoring files, separate from Agent execution."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from sagents.v2.optimization.scoring import ScorerDescriptor, ScoringResult
from sagents.v2.optimization.scorer_runtime import MODEL_API_ENV, ScorerModelAPI


class ScorerExecutionError(RuntimeError):
    pass


class PythonExecutionScorer:
    def __init__(self, *, path, source_hash, descriptor, timeout=120, model_api=None, model_api_factory=None):
        self.path = Path(path).resolve()
        self.source_hash = source_hash
        self.descriptor = ScorerDescriptor.model_validate(descriptor)
        self.timeout = timeout
        self.model_api = ScorerModelAPI.model_validate(model_api) if model_api is not None else None
        self.model_api_factory = model_api_factory
        if model_api is not None and model_api_factory is not None:
            raise ValueError("Choose an explicit model API or a runtime API factory")

    async def score(self, request):
        payload = request.model_dump_json().encode()
        if len(payload) > 32 * 1024 * 1024:
            raise ScorerExecutionError('scoring request exceeds 32 MiB')
        if self.model_api_factory is not None:
            async with self.model_api_factory(request) as api:
                return ScoringResult.model_validate_json(await self._execute(payload, model_api=api))
        return ScoringResult.model_validate_json(await self._execute(payload, model_api=self.model_api))

    async def validate(self):
        result = json.loads(await self._execute(b'', validate=True))
        if result.get('status') != 'passed':
            raise ScorerExecutionError(result.get('error', 'scorer validation failed'))
        return result

    async def _execute(self, payload, *, validate=False, model_api=None):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.source_hash:
            raise ScorerExecutionError('frozen scorer source changed')
        # Do not inherit model credentials from the Desktop process environment.
        environment = {'PATH': os.environ.get('PATH', os.defpath), 'PYTHONIOENCODING': 'utf-8',
                       'LANG': os.environ.get('LANG', 'en_US.UTF-8')}
        # Explicit run connection only, never arbitrary ambient credentials.
        # Import self-tests receive no live API and cannot bill the chosen model.
        if not validate and model_api is not None:
            environment[MODEL_API_ENV] = model_api.worker_environment()
        process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-m',
            'sagents.v2.optimization.python_scorer_worker', str(self.path),
            *(['--validate'] if validate else []),
            cwd=self.path.parent, env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=1024 * 1024 + 1)
        async def write():
            try:
                process.stdin.write(payload + b'\n')
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                # Import/startup failures can close stdin before a large request
                # drains. Read the worker outcome before classifying the failure.
                pass
            finally:
                process.stdin.close()
        try:
            async with asyncio.timeout(self.timeout):
                send = asyncio.create_task(write())
                try:
                    chunks, size = [], 0
                    while chunk := await process.stdout.readline():
                        size += len(chunk)
                        if size > 1024 * 1024:
                            raise ScorerExecutionError('scorer output exceeds 1 MiB')
                        chunks.append(chunk)
                    output = b''.join(chunks)
                    await send
                    code = await process.wait()
                    if code:
                        raise ScorerExecutionError(f'scorer process exited with code {code}')
                    result = json.loads(output)
                    error = result.get('execution_error') if isinstance(result, dict) else None
                    if error is not None:
                        if error.get('retryable') and str(error.get('code', '')).startswith('model.'):
                            from sagents.v2.optimization.recovery import OptimizationTransientFailure
                            raise OptimizationTransientFailure('Scorer ModelProvider transport interrupted')
                        raise ScorerExecutionError('Scorer execution failed: ' + str(error.get('code'))
                            + (' (' + str(error['error_type']) + ')' if error.get('error_type') else ''))
                    return output
                finally:
                    if not send.done():
                        send.cancel()
                        await asyncio.gather(send, return_exceptions=True)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
