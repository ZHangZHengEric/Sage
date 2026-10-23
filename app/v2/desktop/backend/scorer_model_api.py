"""Run-scoped text model API backed by Sage's ModelProvider, without an Agent.

Scorers own all evaluation prompts and parsing. Per-invocation capabilities keep
remote credentials in the sidecar and separate train/dev/test call metadata.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import secrets
import socket
import time

from pydantic import Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelEventKind, ModelMessage, ModelRequest
from sagents.v2.optimization.scorer_runtime import ScorerModelAPI


class _Message(StrictModel):
    role: str
    content: str | list[dict]

    def native(self):
        if self.role not in {'system', 'developer', 'user', 'assistant'}:
            raise ValueError('Only text conversation roles are supported')
        blocks = self.content if isinstance(self.content, list) else [{'type': 'text', 'text': self.content}]
        if any(b.get('type') not in {'text', 'input_text', 'output_text'} or not isinstance(b.get('text'), str) for b in blocks):
            raise ValueError('Scorer model API supports text content only')
        return ModelMessage(role=self.role, content=tuple(TextBlock(text=b['text']) for b in blocks))


class _Request(StrictModel):
    model: str
    input: str | tuple[_Message, ...] | None = None
    messages: tuple[_Message, ...] | None = None
    instructions: str | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    stream: bool = False
    store: bool = False


class _Server(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield

    def install_signal_handlers(self):
        pass


class ScorerModelGateway:
    def __init__(self, *, provider, model, model_binding, run_id, concurrency,
                 model_budget, max_output_tokens=8192, timeout=90, audit=None, redact=()):
        self.provider, self.model, self.model_binding = provider, model, model_binding
        self.run_id, self.concurrency, self.model_budget = run_id, concurrency, model_budget
        self.max_output_tokens, self.timeout, self.audit = max_output_tokens, timeout, audit
        self.redact = tuple(value for value in redact if value)
        self._leases, self._active = {}, set()
        self.server = self.task = self.sock = None
        self.base_url = None
        self.app = Starlette(routes=[Route('/v1/responses', self.complete, methods=['POST']),
                                    Route('/v1/chat/completions', self.complete, methods=['POST']),
                                    Route('/v1/sage/model', self.native_complete, methods=['POST']),
                                    Route('/v1/sage/capabilities', self.capabilities, methods=['GET'])])

    async def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.setblocking(False)
        self.base_url = f'http://127.0.0.1:{self.sock.getsockname()[1]}/v1'
        self.server = _Server(uvicorn.Config(self.app, log_config=None, access_log=False,
            log_level='critical', lifespan='off', timeout_graceful_shutdown=1))
        self.task = asyncio.create_task(self.server.serve(sockets=[self.sock]), name='rsi-scorer-model-api')
        try:
            async with asyncio.timeout(5):
                while not self.server.started:
                    if self.task.done():
                        await self.task
                        raise RuntimeError('Scorer model API did not start')
                    await asyncio.sleep(.005)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self._leases.clear()
        for task in tuple(self._active):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)
        if self.server is not None:
            self.server.should_exit = True
        if self.task is not None:
            try:
                async with asyncio.timeout(3):
                    await asyncio.shield(self.task)
            except TimeoutError:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        if self.sock is not None:
            self.sock.close()
        self.base_url = None

    @asynccontextmanager
    async def bind(self, request):
        if self.base_url is None:
            raise RuntimeError('Scorer model API is not running')
        token = secrets.token_urlsafe(32)
        self._leases[token] = {'case_id': request.case.id, 'split': request.case.split, 'calls': 0}
        try:
            yield ScorerModelAPI(protocol='openai-responses', base_url=self.base_url,
                api_key=token, model=self.model, max_output_tokens=self.max_output_tokens,
                timeout_seconds=self.timeout)
        finally:
            self._leases.pop(token, None)

    @staticmethod
    def error(status, message, code='invalid_request', retryable=False):
        return JSONResponse({'error': {'message': message, 'type': 'model_api_error',
            'code': code, 'retryable': retryable}}, status_code=status)

    async def complete(self, request: Request):
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        lease = self._leases.get(token)
        if lease is None:
            return self.error(401, 'Invalid or expired scorer model capability', 'unauthorized')
        if lease['calls'] >= 16:
            return self.error(429, 'Scorer model call limit exceeded', 'call_limit')
        try:
            chunks, length = [], 0
            async for chunk in request.stream():
                length += len(chunk)
                if length > 2 * 1024 * 1024:
                    return self.error(413, 'Scorer model request exceeds 2 MiB')
                chunks.append(chunk)
            value = _Request.model_validate_json(b''.join(chunks))
            if value.model != self.model or value.stream or value.store:
                raise ValueError('Use the bound model, nonstreaming output and store=false')
            if (value.input is None) == (value.messages is None):
                raise ValueError('Supply exactly one of input or messages')
            messages = value.messages or value.input
            if isinstance(messages, str):
                messages = (_Message(role='user', content=messages),)
            if not messages or len(messages) > 128:
                raise ValueError('Supply 1 to 128 text messages')
            native = tuple(m.native() for m in messages)
            if value.instructions is not None:
                native = (ModelMessage(role='system', content=(TextBlock(text=value.instructions),)), *native)
            limits = [x for x in (value.max_output_tokens, value.max_completion_tokens, value.max_tokens) if x is not None]
            if len(limits) > 1 or (limits and limits[0] > self.max_output_tokens):
                raise ValueError('Use one output limit within the bound model budget')
        except (ValueError, ValidationError):
            return self.error(400, 'Invalid scorer model request: text messages, bound model and output budget are required')
        result = await self._invoke(ModelRequest(request_id=new_id('scorer-input'), run_id=self.run_id,
            model_binding=self.model_binding, messages=native, temperature=value.temperature,
            max_output_tokens=limits[0] if limits else self.max_output_tokens), lease, token)
        if isinstance(result, JSONResponse):
            return result
        usage = {'input_tokens': result.usage.input_tokens, 'output_tokens': result.usage.output_tokens,
                 'total_tokens': result.usage.input_tokens + result.usage.output_tokens}
        if request.url.path.endswith('/chat/completions'):
            return JSONResponse({'id': result.response_id, 'object': 'chat.completion', 'created': int(time.time()),
                'model': self.model, 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': result.text}}],
                'usage': {'prompt_tokens': usage['input_tokens'], 'completion_tokens': usage['output_tokens'], 'total_tokens': usage['total_tokens']}})
        return JSONResponse({'id': result.response_id, 'object': 'response', 'created_at': int(time.time()),
            'status': 'completed', 'model': self.model, 'output': [{'id': new_id('msg'), 'type': 'message',
            'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': result.text, 'annotations': []}]}],
            'usage': usage})

    async def capabilities(self, request):
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if token not in self._leases:
            return self.error(401, 'Invalid or expired scorer model capability', 'unauthorized')
        value = await self.provider.capabilities(self.model_binding)
        value = value.model_copy(update={'supports_streaming': False,
            'max_output_tokens': min(value.max_output_tokens or self.max_output_tokens, self.max_output_tokens)})
        return JSONResponse(value.model_dump(mode='json'))

    async def native_complete(self, request):
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        lease = self._leases.get(token)
        if lease is None:
            return self.error(401, 'Invalid or expired scorer model capability', 'unauthorized')
        try:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    return self.error(413, 'Scorer model request exceeds 2 MiB')
                chunks.append(chunk)
            native = ModelRequest.model_validate_json(b''.join(chunks))
            if native.model_binding not in {self.model, self.model_binding, 'scorer'}:
                raise ValueError('Model binding is not authorized')
            if len(native.messages) > 128 or not native.messages:
                raise ValueError('Supply 1 to 128 messages')
            if native.max_output_tokens is not None and native.max_output_tokens > self.max_output_tokens:
                raise ValueError('Output budget exceeds the bound limit')
        except ValueError:
            return self.error(400, 'Invalid native ModelRequest, binding or output budget')
        result = await self._invoke(native, lease, token, allow_tools=True)
        return result if isinstance(result, JSONResponse) else JSONResponse(result.model_dump(mode='json'))

    async def _invoke(self, native, lease, token, *, allow_tools=False):
        if lease['calls'] >= 16:
            return self.error(429, 'Scorer model call limit exceeded', 'call_limit')
        lease['calls'] += 1
        task = asyncio.current_task()
        self._active.add(task)
        identity, started = new_id('scorer-model'), time.monotonic()
        record = {'request_id': identity, 'case_id': lease['case_id'], 'split': lease['split'],
                  'model': self.model, 'status': 'started'}
        try:
            result = None
            async with asyncio.timeout(self.timeout):
                async with self.concurrency, self.model_budget.lease():
                    stream = self.provider.stream(native.model_copy(update={
                        'request_id': identity, 'run_id': self.run_id, 'model_binding': self.model_binding,
                        'max_output_tokens': native.max_output_tokens or self.max_output_tokens,
                        'metadata': {**native.metadata, 'purpose': 'scorer',
                                     'case_id': lease['case_id'], 'split': lease['split']}}))
                    try:
                        async for event in stream:
                            if event.kind == ModelEventKind.COMPLETED:
                                result = event.response
                    finally:
                        close = getattr(stream, 'aclose', None)
                        if close is not None:
                            await close()
            if result is None or (result.tool_calls and not allow_tools) or result.finish_reason in {'length', 'max_tokens', 'incomplete'}:
                record.update(status='failed', error_type='model.incomplete')
                return self.error(502, 'Model did not complete a text response', 'model.incomplete', True)
            record.update(status='completed', usage=result.usage.model_dump(mode='json', exclude={'provider_usage'}))
            return result
        except SageV2Error as error:
            record.update(status='failed', error_type=error.info.code)
            message = error.info.message[:2000]
            for value in (*self.redact, token):
                message = message.replace(value, '[redacted]')
            record.update(error_message=message, provider_code=error.info.provider_code,
                retryable=error.info.retryable,
                response_started=error.info.metadata.get('response_started'))
            status = 503 if error.info.retryable else 400
            return self.error(status, message, error.info.code, error.info.retryable)
        except TimeoutError:
            record.update(status='failed', error_type='model.timeout')
            return self.error(504, 'Scorer model call timed out', 'model.timeout', True)
        except Exception:
            record.update(status='failed', error_type='model.internal')
            return self.error(502, 'Scorer model transport failed', 'model.internal', True)
        finally:
            self._active.discard(task)
            record['elapsed_seconds'] = time.monotonic() - started
            if self.audit is not None:
                self.audit(record)
