from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator, Mapping
from typing import Any, Dict, Optional

from loguru import logger

from common.core.exceptions import SageHTTPException
from common.models.agent import Agent, AgentConfigDao
from common.models.llm_provider import LLMProvider, LLMProviderDao
from common.schemas.model_invocation import (
    ATTRIBUTION_METADATA_KEYS,
    DirectModelInvokeRequest,
)
from common.services import token_usage_service
from common.services.chat_utils import create_model_client
from sagents.llm.model_capabilities import (
    is_openai_reasoning_model,
    resolve_reasoning_effort,
)
from sagents.utils.llm_request_utils import (
    create_chat_completion_with_fallback,
    redact_base64_data_urls_in_value,
)

_INTERNAL_REQUEST_FIELDS = {
    "agent_id",
    "provider_id",
    "user_id",
    "model_type",
    "task",
    "metadata",
    "messages",
    "stream",
    "deep_thinking",
    "thinking_level",
    "deep_thinking_level",
}
_PROVIDER_CONFIG_FIELDS = {
    "api_key",
    "api_keys",
    "base_url",
    "fast_api_key",
    "fast_base_url",
    "fast_model_name",
    "maxTokens",
    "max_model_len",
    "model",
}


def _get_provider_api_key(provider: LLMProvider) -> str:
    api_key = provider.api_key
    if not api_key:
        raise SageHTTPException(
            status_code=400,
            detail="Provider API key is missing",
            error_detail=f"provider_id={provider.id}",
        )
    return api_key


def _provider_to_model_config(provider: LLMProvider) -> Dict[str, Any]:
    return {
        "base_url": provider.base_url,
        "api_key": _get_provider_api_key(provider),
        "model": provider.model,
        "max_tokens": provider.max_tokens,
        "temperature": provider.temperature,
        "top_p": provider.top_p,
        "presence_penalty": provider.presence_penalty,
        "max_model_len": provider.max_model_len,
        "supports_multimodal": provider.supports_multimodal,
        "supports_structured_output": provider.supports_structured_output,
    }


def _strip_none_values(data: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


async def _resolve_agent(
    request: DirectModelInvokeRequest,
) -> Optional[Agent]:
    if not request.agent_id:
        return None
    agent = await AgentConfigDao().get_by_id(request.agent_id)
    if not agent or not agent.config:
        logger.warning(f"[DirectModelInvoke] Agent {request.agent_id} not found")
        return None
    return agent


async def _resolve_provider(
    request: DirectModelInvokeRequest, agent: Optional[Agent]
) -> tuple[LLMProvider, Optional[LLMProvider]]:
    if request.provider_id:
        provider = await LLMProviderDao().get_by_id(request.provider_id)
        if provider is None:
            raise SageHTTPException(
                status_code=404,
                detail="Provider not found",
                error_detail=f"provider_id={request.provider_id}",
            )
        return provider, None

    if agent is not None:
        provider_id = str(agent.config.get("llm_provider_id") or "").strip()
        if not provider_id:
            raise SageHTTPException(
                status_code=400,
                detail="Agent LLM provider is missing",
                error_detail=f"agent_id={agent.agent_id}",
            )
        provider = await LLMProviderDao().get_by_id(provider_id)
        if provider is None:
            raise SageHTTPException(
                status_code=404,
                detail="Agent LLM provider not found",
                error_detail=f"agent_id={agent.agent_id}, provider_id={provider_id}",
            )

        fast_provider = None
        fast_provider_id = str(agent.config.get("fast_llm_provider_id") or "").strip()
        if fast_provider_id:
            fast_provider = await LLMProviderDao().get_by_id(fast_provider_id)
            if fast_provider is None:
                raise SageHTTPException(
                    status_code=404,
                    detail="Agent fast LLM provider not found",
                    error_detail=(
                        f"agent_id={agent.agent_id}, provider_id={fast_provider_id}"
                    ),
                )
        return provider, fast_provider

    raise SageHTTPException(
        status_code=400,
        detail="Provider is required",
        error_detail="provider_id or agent LLM provider is required",
    )


def _resolve_runtime_user_id(
    request: DirectModelInvokeRequest, config_user_id: str
) -> str:
    body_user_id = str(request.user_id or "").strip()
    return body_user_id or config_user_id


def _build_model_config(
    provider: LLMProvider,
    fast_provider: Optional[LLMProvider],
    *,
    model_type: str,
) -> Dict[str, Any]:
    model_config = _provider_to_model_config(provider)
    if fast_provider is not None:
        model_config["fast_api_key"] = _get_provider_api_key(fast_provider)
        model_config["fast_base_url"] = fast_provider.base_url
        model_config["fast_model_name"] = fast_provider.model
    active_provider = (
        fast_provider if model_type == "fast" and fast_provider is not None else provider
    )
    active_config = _provider_to_model_config(active_provider)
    for key in (
        "max_tokens",
        "temperature",
        "top_p",
        "presence_penalty",
        "max_model_len",
        "supports_multimodal",
        "supports_structured_output",
    ):
        model_config[key] = active_config.get(key)
    return _strip_none_values(model_config)


def _build_openai_request_kwargs(
    request: DirectModelInvokeRequest, model_config: Dict[str, Any]
) -> Dict[str, Any]:
    request_data = request.model_dump(exclude_none=True, by_alias=False)
    kwargs: Dict[str, Any] = {}

    for key, value in model_config.items():
        if key not in _PROVIDER_CONFIG_FIELDS and not key.startswith("supports_"):
            kwargs[key] = value

    for key, value in request_data.items():
        if key in _INTERNAL_REQUEST_FIELDS or key in _PROVIDER_CONFIG_FIELDS:
            continue
        kwargs[key] = value

    extra = request.model_extra or {}
    for key, value in extra.items():
        if key in _INTERNAL_REQUEST_FIELDS or key in _PROVIDER_CONFIG_FIELDS:
            continue
        kwargs[key] = value

    kwargs["model_type"] = request.model_type
    if request.response_format is not None:
        kwargs["response_format"] = request.response_format
    return _strip_none_values(kwargs)


def _build_thinking_extra_body(
    *,
    existing_extra_body: Any,
    model: str,
    task: Optional[str],
    deep_thinking: Optional[bool],
    thinking_level: Optional[str],
) -> Dict[str, Any]:
    extra_body = (
        dict(existing_extra_body) if isinstance(existing_extra_body, dict) else {}
    )
    extra_body.setdefault("_step_name", task or "direct_model_invocation")

    enable_thinking = bool(deep_thinking)
    if thinking_level:
        enable_thinking = True

    if is_openai_reasoning_model(model):
        if thinking_level:
            extra_body["reasoning_effort"] = thinking_level
        else:
            extra_body["reasoning_effort"] = resolve_reasoning_effort(
                enable_thinking=enable_thinking,
                env_value=None,
                default_off="low",
            )
        return extra_body

    if deep_thinking is None and thinking_level is None:
        return extra_body

    extra_body["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
    extra_body["enable_thinking"] = enable_thinking
    extra_body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
    return extra_body


def _sanitize_for_log(value: Any, *, max_depth: int = 4, max_items: int = 12) -> Any:
    if max_depth < 0:
        return f"<{type(value).__name__}>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        redacted = redact_base64_data_urls_in_value(value)
        if not isinstance(redacted, str):
            return redacted
        if len(redacted) <= 200:
            return redacted
        return redacted[:197] + "..."
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:max_items]:
            key_str = str(key)
            if any(
                token in key_str.lower()
                for token in ("key", "token", "secret", "password", "authorization")
            ):
                result[key_str] = "<redacted>"
            else:
                result[key_str] = _sanitize_for_log(
                    item,
                    max_depth=max_depth - 1,
                    max_items=max_items,
                )
        if len(items) > max_items:
            result["..."] = f"+{len(items) - max_items} more"
        return result
    if isinstance(value, (list, tuple)):
        items = list(value)
        result = [
            _sanitize_for_log(item, max_depth=max_depth - 1, max_items=max_items)
            for item in items[:max_items]
        ]
        if len(items) > max_items:
            result.append(f"... +{len(items) - max_items} more")
        return result
    return f"<{type(value).__name__}>"


def _truncate_attribution(value: str, limit: int = 128) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def _resolve_attribution(request: DirectModelInvokeRequest) -> str:
    task = str(request.task or "").strip()
    if task:
        return _truncate_attribution(task)
    for key in ATTRIBUTION_METADATA_KEYS:
        value = str(request.metadata.get(key) or "").strip()
        if value:
            return _truncate_attribution(value)
    return "direct_model_invocation"


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, Mapping):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def _extract_usage(response: Any) -> Optional[Dict[str, Any]]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, Mapping):
        usage = response.get("usage")
    if usage is None:
        return None
    data = _to_jsonable(usage)
    return data if isinstance(data, dict) else None


def _usage_payload(
    *,
    usage: Optional[Dict[str, Any]],
    task: str,
    model: str,
) -> Optional[Dict[str, Any]]:
    if not usage or not isinstance(usage.get("total_tokens"), int):
        return None
    return {
        "total_info": usage,
        "per_step_info": [
            {
                "step_name": task,
                "model": model,
                "usage": usage,
            }
        ],
    }


async def _record_usage(
    *,
    usage: Optional[Dict[str, Any]],
    task: str,
    model: str,
    invocation_id: str,
    user_id: str,
    agent_id: Optional[str],
    started_at: float,
) -> None:
    payload = _usage_payload(usage=usage, task=task, model=model)
    if payload is None:
        return
    try:
        await token_usage_service.record_execution_payload(
            token_usage=payload,
            request_source=task,
            session_id=invocation_id,
            user_id=user_id,
            agent_id=agent_id,
            started_at=started_at,
            finished_at=time.time(),
        )
    except Exception as exc:
        logger.warning(f"[DirectModelInvoke] Failed to record token usage: {exc}")


def _model_for_request(model_config: Dict[str, Any], model_type: str) -> str:
    if model_type == "fast" and model_config.get("fast_model_name"):
        return str(model_config["fast_model_name"])
    return str(model_config.get("model") or "gpt-3.5-turbo")


async def invoke_model(
    request: DirectModelInvokeRequest,
    *,
    user_id: str,
) -> Dict[str, Any]:
    started_at = time.time()
    invocation_id = f"direct_model_{uuid.uuid4().hex}"
    runtime_user_id = _resolve_runtime_user_id(request, user_id)
    agent = await _resolve_agent(request)
    provider, fast_provider = await _resolve_provider(request, agent)
    model_config = _build_model_config(
        provider,
        fast_provider,
        model_type=request.model_type,
    )
    model_name = _model_for_request(model_config, request.model_type)
    attribution = _resolve_attribution(request)
    kwargs = _build_openai_request_kwargs(request, model_config)
    kwargs["extra_body"] = _build_thinking_extra_body(
        existing_extra_body=kwargs.get("extra_body"),
        model=model_name,
        task=attribution,
        deep_thinking=request.deep_thinking,
        thinking_level=request.thinking_level,
    )
    kwargs["stream"] = False

    client = create_model_client(model_config)
    try:
        logger.info(
            "[DirectModelInvoke] invoke "
            f"task={request.task}, user_id={runtime_user_id}, agent_id={request.agent_id}, "
            f"provider_id={provider.id}, model_type={request.model_type}, model={model_name}, "
            f"metadata={_sanitize_for_log(request.metadata)}"
        )
        response = await create_chat_completion_with_fallback(
            client,
            model=model_name,
            messages=_to_jsonable(request.messages),
            model_config=model_config,
            response_format=kwargs.pop("response_format", None),
            **kwargs,
        )
        result = _to_jsonable(response)
        if isinstance(result, dict):
            result["provider_id"] = provider.id
            result["model_type"] = request.model_type
            result["task"] = request.task
            result["request_source"] = attribution
            result["invocation_id"] = invocation_id
        usage = _extract_usage(response)
        await _record_usage(
            usage=usage,
            task=attribution,
            model=model_name,
            invocation_id=invocation_id,
            user_id=runtime_user_id,
            agent_id=request.agent_id,
            started_at=started_at,
        )
        return result if isinstance(result, dict) else {"response": result}
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            await close()


async def stream_model(
    request: DirectModelInvokeRequest,
    *,
    user_id: str,
) -> AsyncGenerator[str, None]:
    started_at = time.time()
    invocation_id = f"direct_model_{uuid.uuid4().hex}"
    runtime_user_id = _resolve_runtime_user_id(request, user_id)
    agent = await _resolve_agent(request)
    provider, fast_provider = await _resolve_provider(request, agent)
    model_config = _build_model_config(
        provider,
        fast_provider,
        model_type=request.model_type,
    )
    model_name = _model_for_request(model_config, request.model_type)
    attribution = _resolve_attribution(request)
    kwargs = _build_openai_request_kwargs(request, model_config)
    kwargs["extra_body"] = _build_thinking_extra_body(
        existing_extra_body=kwargs.get("extra_body"),
        model=model_name,
        task=attribution,
        deep_thinking=request.deep_thinking,
        thinking_level=request.thinking_level,
    )
    kwargs["stream"] = True
    stream_options = dict(kwargs.get("stream_options") or {})
    stream_options["include_usage"] = True
    kwargs["stream_options"] = stream_options

    client = create_model_client(model_config)
    usage: Optional[Dict[str, Any]] = None
    try:
        logger.info(
            "[DirectModelInvoke] stream "
            f"task={request.task}, user_id={runtime_user_id}, agent_id={request.agent_id}, "
            f"provider_id={provider.id}, model_type={request.model_type}, model={model_name}, "
            f"metadata={_sanitize_for_log(request.metadata)}"
        )
        stream = await create_chat_completion_with_fallback(
            client,
            model=model_name,
            messages=_to_jsonable(request.messages),
            model_config=model_config,
            response_format=kwargs.pop("response_format", None),
            **kwargs,
        )
        async for chunk in stream:
            chunk_data = _to_jsonable(chunk)
            if isinstance(chunk_data, dict):
                chunk_data["provider_id"] = provider.id
                chunk_data["model_type"] = request.model_type
                chunk_data["task"] = request.task
                chunk_data["request_source"] = attribution
                chunk_data["invocation_id"] = invocation_id
            usage = _extract_usage(chunk) or usage
            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
        await _record_usage(
            usage=usage,
            task=attribution,
            model=model_name,
            invocation_id=invocation_id,
            user_id=runtime_user_id,
            agent_id=request.agent_id,
            started_at=started_at,
        )
        yield "data: [DONE]\n\n"
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            await close()
