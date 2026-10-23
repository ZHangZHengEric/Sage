"""Runtime model API access for user-authored scorers, without scoring policy.

The scorer owns prompts, calls, retries, parsing and numerical evaluation. This
module only describes the explicitly selected model connection. It never invokes
RSI's evaluator, and credentials are not part of scoring requests or reports.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from sagents.v2.contracts.common import StrictModel

MODEL_API_ENV = 'SAGE_RSI_SCORER_MODEL_API'
# Private import-validation override; absent in real scoring workers.
_TEST_MODEL = ContextVar('scorer_test_model', default=None)


class ScorerModelAPI(StrictModel):
    protocol: Literal['openai-responses', 'openai-chat-completions',
                      'anthropic-messages', 'gemini-generate-content']
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: SecretStr
    max_output_tokens: int = Field(default=8192, ge=1)
    timeout_seconds: float = Field(default=90, gt=0, allow_inf_nan=False)

    @field_validator('base_url')
    @classmethod
    def absolute_http_url(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('scorer model API requires an absolute HTTP(S) URL')
        return value

    def worker_environment(self):
        """Private process transport; never save this value in journals/reports."""
        import json
        return json.dumps({**self.model_dump(mode='json'), 'api_key': self.api_key.get_secret_value()})


def get_model_api() -> ScorerModelAPI:
    """Return the run's shared model connection; make no model call."""
    value = os.environ.get(MODEL_API_ENV)
    if not value:
        raise RuntimeError('No scorer model API is available in this runtime')
    return ScorerModelAPI.model_validate_json(value)


class ScorerModelProvider:
    """ModelProvider port available inside an isolated scoring subprocess.

    Messages and request controls are passed verbatim. Only the host-owned model
    binding, run identity, call budget and evidence scope are enforced remotely.
    """
    plugin_id = 'sage.model.scorer-proxy'
    name = 'Scorer ModelProvider'

    def __init__(self, api):
        self._api = api
        self.model_binding = api.model

    async def _request(self, path, payload=None):
        import asyncio
        import httpx
        from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
        headers = {'Authorization': 'Bearer ' + self._api.api_key.get_secret_value()}
        async with asyncio.timeout(self._api.timeout_seconds):
            async with httpx.AsyncClient(timeout=self._api.timeout_seconds) as client:
                for attempt in range(3):
                    try:
                        response = await client.request('GET' if payload is None else 'POST',
                            self._api.base_url + path, headers=headers, json=payload)
                    except httpx.TransportError:
                        error = RuntimeErrorInfo(code='model.provider_transient', category=ErrorCategory.PROVIDER_TRANSIENT,
                            message='Scorer model transport interrupted', retryable=True, safe_to_resume=True)
                    else:
                        if response.is_success:
                            return response.json()
                        try:
                            body = response.json().get('error', {})
                        except (ValueError, AttributeError):
                            body = {}
                        if not isinstance(body, dict):
                            body = {}
                        retryable = bool(body.get('retryable', response.status_code >= 500))
                        error = RuntimeErrorInfo(code=body.get('code', 'model.provider_error'),
                            category=ErrorCategory.PROVIDER_TRANSIENT if retryable else ErrorCategory.VALIDATION,
                            message=body.get('message', 'Scorer model request failed'),
                            retryable=retryable, safe_to_resume=True)
                    if not error.retryable or attempt == 2:
                        raise SageV2Error(error)
                    await asyncio.sleep(.25 * (2 ** attempt))

    async def capabilities(self, model_binding):
        from sagents.v2.model.contracts import ModelCapabilities
        return ModelCapabilities.model_validate(await self._request('/sage/capabilities'))

    async def stream(self, request):
        from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
        try:
            result = await self._request('/sage/model', request.model_dump(mode='json'))
        except TimeoutError as error:
            from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
            raise SageV2Error(RuntimeErrorInfo(code='model.provider_transient',
                category=ErrorCategory.PROVIDER_TRANSIENT, message='Scorer ModelProvider timed out',
                retryable=True, safe_to_resume=True)) from error
        yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse.model_validate(result))

    async def close(self):
        # Each request owns and closes its client; this object owns no backend.
        pass


def get_model_provider() -> ScorerModelProvider:
    """Return a ready ModelProvider proxy; never create an evaluator Agent."""
    override = _TEST_MODEL.get()
    return override if override is not None else ScorerModelProvider(get_model_api())


def _test_model(responses):
    from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep
    if not isinstance(responses, (list, tuple)) or not 1 <= len(responses) <= 16:
        raise ValueError('model_responses must contain 1 to 16 recorded ModelResponse objects')
    provider = ScriptedModelProvider(tuple(ScriptedModelStep(events=(ModelStreamEvent(
        kind=ModelEventKind.COMPLETED, response=ModelResponse.model_validate(value)),)) for value in responses))
    provider.model_binding = 'scorer-fixture'
    return provider
