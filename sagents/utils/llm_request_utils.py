from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, Mapping, Optional

from openai import APIError

from .logger import logger


def uses_max_completion_tokens(model: Optional[str]) -> bool:
    """
    部分 OpenAI 模型（o1/o3、GPT-5 等）的 Chat Completions API 仅接受
    max_completion_tokens，传入 max_tokens 会返回 unsupported_parameter。
    """
    m = (model or "").strip().lower()
    if not m:
        return False
    if m.startswith("o1") or m.startswith("o3"):
        return True
    # GPT-5 家族（含 gpt-5.4-mini 等）
    if "gpt-5" in m:
        return True
    return False


def _remap_max_tokens_for_model(request_kwargs: Dict[str, Any], model: Optional[str]) -> None:
    if not uses_max_completion_tokens(model):
        return
    if "max_tokens" not in request_kwargs:
        return
    mt = request_kwargs.pop("max_tokens")
    # 若调用方已显式设置 max_completion_tokens，以显式值为准
    if request_kwargs.get("max_completion_tokens") is None and mt is not None:
        request_kwargs["max_completion_tokens"] = mt


def _extract_bool_flag(source: Any, key: str) -> Optional[bool]:
    if source is None:
        return None

    if isinstance(source, Mapping):
        value = source.get(key)
    else:
        value = getattr(source, key, None)
        if value is None:
            model_capabilities = getattr(source, "model_capabilities", None)
            if isinstance(model_capabilities, Mapping):
                value = model_capabilities.get(key)

    if value is None:
        return None
    return bool(value)


def get_structured_output_support(
    client: Any = None,
    model_config: Optional[Dict[str, Any]] = None,
) -> Optional[bool]:
    """
    尝试从客户端或模型配置中读取结构化输出能力。

    返回值语义：
    - True: 明确支持
    - False: 明确不支持
    - None: 未知
    """
    config_flag = _extract_bool_flag(model_config, "supports_structured_output")
    if config_flag is not None:
        return config_flag

    client_flag = _extract_bool_flag(client, "supports_structured_output")
    if client_flag is not None:
        return client_flag

    return None


def sanitize_model_request_kwargs(
    request_kwargs: Dict[str, Any],
    *,
    client: Any = None,
    model_config: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    基于已知能力过滤不支持的请求参数。

    当前先处理 structured output / response_format：
    - 如果明确不支持 structured output，则移除 response_format。
    - 如果能力未知，则保留，交给运行时 fallback 兜底。

    另：对仅支持 max_completion_tokens 的模型，将 max_tokens 映射为该参数。
    """
    sanitized = dict(request_kwargs)
    for key in list(sanitized.keys()):
        if str(key).startswith("supports_"):
            sanitized.pop(key, None)
    # 前端可能将采样参数置空（None / 空串），不应作为请求字段下发到大模型，
    # 否则部分后端（如 OpenAI）会因为 null 值或多余字段返回 invalid_request_error。
    _empty_droppable_keys = (
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "max_model_len",
    )
    for key in _empty_droppable_keys:
        if key in sanitized and (sanitized[key] is None or sanitized[key] == ""):
            sanitized.pop(key, None)
    resolved_model = model
    if resolved_model is None:
        resolved_model = sanitized.get("model")
        if not isinstance(resolved_model, str):
            resolved_model = None
    _remap_max_tokens_for_model(sanitized, resolved_model)
    structured_support = get_structured_output_support(client=client, model_config=model_config)
    if structured_support is False:
        sanitized.pop("response_format", None)
    return sanitized


def is_unsupported_input_format_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "unsupported input format" in error_text
        or "unsupported_input_format" in error_text
        or ("invalidparameter" in error_text and "input format" in error_text)
    )


def format_api_error_details(exc: APIError) -> str:
    parts = [f"type={type(exc).__name__}", f"message={exc}"]
    code = getattr(exc, "code", None)
    param = getattr(exc, "param", None)
    body = getattr(exc, "body", None)
    request = getattr(exc, "request", None)

    if code is not None:
        parts.append(f"code={code}")
    if param is not None:
        parts.append(f"param={param}")
    if request is not None:
        method = getattr(request, "method", None)
        url = getattr(request, "url", None)
        if method:
            parts.append(f"method={method}")
        if url:
            parts.append(f"url={url}")
    if body is not None:
        parts.append(f"body={body!r}")
    return " | ".join(parts)


def _truncate_text(value: str, limit: int = 160) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def redact_base64_data_urls_in_value(value: Any) -> Any:
    """用于日志/追踪：将 ``data:*;base64,...`` 整段替换为占位符，避免泄露图片载荷。"""
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            comma = value.find(",")
            b64_len = (len(value) - comma - 1) if comma >= 0 else 0
            return f"<redacted data URL; base64_len={b64_len}>"
        return value
    if isinstance(value, Mapping):
        return {k: redact_base64_data_urls_in_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        seq = [redact_base64_data_urls_in_value(v) for v in value]
        return type(value)(seq)
    return value


def _sanitize_for_log(value: Any, *, max_depth: int = 2, max_items: int = 8) -> Any:
    if max_depth < 0:
        return f"<{type(value).__name__}>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            return redact_base64_data_urls_in_value(value)
        return _truncate_text(value)

    if isinstance(value, Mapping):
        items = list(value.items())
        result: Dict[str, Any] = {}
        for key, item in items[:max_items]:
            key_str = str(key)
            if any(token in key_str.lower() for token in ("key", "token", "secret", "password", "authorization")):
                result[key_str] = "<redacted>"
            else:
                result[key_str] = _sanitize_for_log(item, max_depth=max_depth - 1, max_items=max_items)
        if len(items) > max_items:
            result["..."] = f"+{len(items) - max_items} more"
        return result

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
        result = [_sanitize_for_log(item, max_depth=max_depth - 1, max_items=max_items) for item in items[:max_items]]
        if len(items) > max_items:
            result.append(f"... +{len(items) - max_items} more")
        return result

    return f"<{type(value).__name__}>"


def summarize_chat_completion_messages(messages: Any) -> Any:
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes, bytearray)):
        return _sanitize_for_log(messages)

    summary = []
    for index, message in enumerate(messages):
        if isinstance(message, Mapping):
            content = message.get("content")
            item: Dict[str, Any] = {
                "index": index,
                "role": message.get("role"),
            }
            if isinstance(content, str):
                item["content_type"] = "str"
                item["content_len"] = len(content)
            elif isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
                item["content_type"] = "list"
                item["content_len"] = len(content)
                item["content_preview"] = _sanitize_for_log(content, max_depth=1)
            else:
                item["content_type"] = type(content).__name__

            if message.get("tool_calls") is not None:
                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes, bytearray)):
                    item["tool_calls_len"] = len(tool_calls)
                else:
                    item["tool_calls_type"] = type(tool_calls).__name__
            summary.append(item)
        else:
            summary.append({"index": index, "type": type(message).__name__})
    return summary


def summarize_chat_completion_request(
    *,
    model: str,
    messages: Any,
    request_kwargs: Mapping[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sanitized_kwargs = _sanitize_for_log(dict(request_kwargs))
    summary: Dict[str, Any] = {
        "model": model,
        # "messages": summarize_chat_completion_messages(messages),
        "request_kwargs": sanitized_kwargs,
    }
    if model_config is not None:
        summary["model_config"] = _sanitize_for_log(model_config)
    return summary


async def create_chat_completion_with_fallback(
    client: Any,
    *,
    model: str,
    messages: Any,
    model_config: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Any:
    """
    调用 chat.completions.create，并在结构化输出不被后端支持时自动降级一次。
    """
    request_kwargs = dict(kwargs)
    if response_format is not None:
        request_kwargs["response_format"] = response_format

    request_kwargs = sanitize_model_request_kwargs(
        request_kwargs,
        client=client,
        model_config=model_config,
        model=model,
    )

    logger.info(
        f"[LLM Request] chat.completions.create | summary={summarize_chat_completion_request(model=model, messages=messages, request_kwargs=request_kwargs, model_config=model_config)}"
    )

    try:
        return await client.chat.completions.create(
            model=model,
            messages=messages,
            **request_kwargs,
        )
    except APIError as exc:
        if response_format is not None and "response_format" in request_kwargs and is_unsupported_input_format_error(exc):
            logger.warning(
                f"模型后端不支持 structured output，自动移除 response_format 后重试: model={model}, details={format_api_error_details(exc)}"
            )
            retry_kwargs = dict(request_kwargs)
            retry_kwargs.pop("response_format", None)
            logger.info(
                f"[LLM Request] chat.completions.create retry_without_response_format | summary={summarize_chat_completion_request(model=model, messages=messages, request_kwargs=retry_kwargs, model_config=model_config)}"
            )
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                **retry_kwargs,
            )
        raise
