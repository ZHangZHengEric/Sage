from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import unquote, urlparse

from openai import APIError

from .logger import logger


_REASONING_MODEL_PREFIXES: tuple[str, ...] = (
    "o1-",
    "o3-",
    "o4-",
    "gpt-5",
)
_REASONING_MODEL_EXACT: frozenset[str] = frozenset({"o1", "o3", "o4"})
_RETIRED_DEEPSEEK_MODEL_ALIASES: frozenset[str] = frozenset(
    {"deepseek-chat", "deepseek-reasoner"}
)


def _is_openai_reasoning_model_name(model: Optional[str]) -> bool:
    """与 ``sagents.llm.model_capabilities.is_openai_reasoning_model`` 判定一致（避免循环/包初始化副作用）。"""
    if not model:
        return False
    name = model.strip().lower()
    if not name:
        return False
    if name in _REASONING_MODEL_EXACT:
        return True
    return any(name.startswith(p) for p in _REASONING_MODEL_PREFIXES)


def _is_deepseek_model_name(model: Optional[str]) -> bool:
    if not model:
        return False
    name = model.strip().lower()
    return (
        name.startswith("deepseek-")
        or name.startswith("deepseek/")
        or "/deepseek-" in name
    )


def _provider_base_url(
    client: Any = None,
    model_config: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    if isinstance(model_config, Mapping) and model_config.get("base_url"):
        return str(model_config["base_url"])
    for candidate in (
        client,
        getattr(client, "_model", None),
        getattr(client, "_standard", None),
    ):
        if candidate is None:
            continue
        value = getattr(candidate, "base_url", None) or getattr(
            candidate, "_base_url", None
        )
        if value:
            return str(value)
    return None


def _uses_deepseek_native_protocol(
    model: Optional[str],
    *,
    client: Any = None,
    model_config: Optional[Mapping[str, Any]] = None,
) -> bool:
    if not _is_deepseek_model_name(model):
        return False
    base_url = _provider_base_url(client=client, model_config=model_config)
    if not base_url:
        return False
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    return (parsed.hostname or "").lower() == "api.deepseek.com"


def normalize_chat_completions_model(
    model: str,
    *,
    client: Any = None,
    model_config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Resolve retired first-party DeepSeek aliases at the request boundary.

    DeepSeek documented both legacy names as aliases of V4 Flash before their
    retirement. Keep saved Sage providers working without mutating their durable
    configuration; third-party endpoints with the same slugs remain untouched.
    """
    normalized = str(model or "").strip()
    if (
        normalized.lower() in _RETIRED_DEEPSEEK_MODEL_ALIASES
        and _uses_deepseek_native_protocol(
            normalized, client=client, model_config=model_config
        )
    ):
        logger.warning(
            f"DeepSeek model alias {normalized!r} is retired; "
            "using 'deepseek-v4-flash' for this Chat Completions request",
            session_id="NO_SESSION",
        )
        return "deepseek-v4-flash"
    return normalized


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


def _remap_max_tokens_for_model(
    request_kwargs: Dict[str, Any], model: Optional[str]
) -> None:
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


def get_multimodal_support(
    client: Any = None,
    model_config: Optional[Dict[str, Any]] = None,
) -> Optional[bool]:
    config_flag = _extract_bool_flag(model_config, "supports_multimodal")
    if config_flag is not None:
        return config_flag

    client_flag = _extract_bool_flag(client, "supports_multimodal")
    if client_flag is not None:
        return client_flag

    return None


def _extract_image_url_part_url(item: Mapping[str, Any]) -> str:
    image_url = item.get("image_url")
    if isinstance(image_url, Mapping):
        return str(image_url.get("url") or "").strip()
    if isinstance(image_url, str):
        return image_url.strip()
    return str(item.get("url") or "").strip()


def _append_text_part(content: list[Any], text: str) -> None:
    if not text:
        return
    if content and isinstance(content[-1], dict) and content[-1].get("type") == "text":
        content[-1]["text"] = str(content[-1].get("text") or "") + text
        return
    content.append({"type": "text", "text": text})


def _markdown_image_reference_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(Path(parsed.path).name) if parsed.path else ""
    if not name or url.startswith("data:image/"):
        name = "image"
    escaped_name = name.replace("]", "\\]")
    return f"![{escaped_name}]({url})"


def _downgrade_multimodal_content_list(content: Sequence[Any]) -> tuple[list[Any], int]:
    downgraded = 0
    new_content: list[Any] = []
    content_list = list(content)
    for index, item in enumerate(content_list):
        if not isinstance(item, Mapping):
            new_content.append(item)
            continue

        if item.get("type") != "image_url":
            if item.get("type") == "text":
                _append_text_part(new_content, str(item.get("text") or ""))
            else:
                new_content.append(dict(item))
            continue

        url = _extract_image_url_part_url(item)
        if url:
            next_item = (
                content_list[index + 1] if index + 1 < len(content_list) else None
            )
            next_text = (
                str(next_item.get("text") or "")
                if isinstance(next_item, Mapping) and next_item.get("type") == "text"
                else ""
            )
            if url not in next_text:
                _append_text_part(
                    new_content,
                    _markdown_image_reference_from_url(url),
                )
        downgraded += 1

    return new_content, downgraded


def downgrade_image_url_parts_for_text_only_model(messages: Any) -> tuple[Any, int]:
    """
    Remove ``image_url`` content parts before calling a model that is explicitly
    known to be text-only. If a removed image has no adjacent markdown reference,
    keep a markdown URL reference as plain text.
    """
    if not isinstance(messages, Sequence) or isinstance(
        messages, (str, bytes, bytearray)
    ):
        return messages, 0

    downgraded = 0
    changed = False
    new_messages: list[Any] = []
    for message in messages:
        if not isinstance(message, Mapping):
            new_messages.append(message)
            continue

        content = message.get("content")
        if not isinstance(content, Sequence) or isinstance(
            content, (str, bytes, bytearray)
        ):
            new_messages.append(message)
            continue

        new_content, message_downgraded = _downgrade_multimodal_content_list(content)
        if not message_downgraded:
            new_messages.append(message)
            continue

        message_copy = dict(message)
        message_copy["content"] = new_content if new_content else ""
        new_messages.append(message_copy)
        downgraded += message_downgraded
        changed = True

    if not changed:
        return messages, 0
    return new_messages, downgraded


def _tool_choice_is_required(tool_choice: Any) -> bool:
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower() == "required"
    return False


def _drop_reasoning_effort_when_tools_present(
    sanitized: Dict[str, Any], model: Optional[str]
) -> None:
    """
    OpenAI：gpt-5.4 等在 chat/completions 上，只要请求携带 tools，
    extra_body.reasoning_effort 就会触发 invalid_request_error，与 tool_choice 无关。
    """
    if not model or not _is_openai_reasoning_model_name(model):
        return
    tools = sanitized.get("tools")
    has_tools = isinstance(tools, (list, tuple)) and len(tools) > 0
    if not has_tools:
        return
    eb = sanitized.get("extra_body")
    if not isinstance(eb, dict) or "reasoning_effort" not in eb:
        return
    sanitized["extra_body"] = {k: v for k, v in eb.items() if k != "reasoning_effort"}
    logger.debug(
        "sanitize_model_request_kwargs: dropped reasoning_effort from extra_body "
        "(tools present, chat/completions compatibility)",
        session_id="NO_SESSION",
    )


def _drop_tool_choice_for_deepseek_thinking(
    sanitized: Dict[str, Any],
    model: Optional[str],
    *,
    client: Any = None,
    model_config: Optional[Mapping[str, Any]] = None,
) -> None:
    """DeepSeek V4 thinking supports tools but rejects ``tool_choice``."""
    if not _uses_deepseek_native_protocol(
        model, client=client, model_config=model_config
    ) or "tool_choice" not in sanitized:
        return
    tools = sanitized.get("tools")
    if not isinstance(tools, (list, tuple)) or not tools:
        return

    extra_body = sanitized.get("extra_body")
    extra_body = extra_body if isinstance(extra_body, dict) else {}
    thinking = extra_body.get("thinking")
    thinking_type = (
        str(thinking.get("type") or "").strip().lower()
        if isinstance(thinking, Mapping)
        else ""
    )
    explicitly_disabled = thinking_type == "disabled"
    explicitly_disabled = explicitly_disabled or extra_body.get(
        "enable_thinking"
    ) is False
    template_kwargs = extra_body.get("chat_template_kwargs")
    explicitly_disabled = explicitly_disabled or (
        isinstance(template_kwargs, Mapping)
        and template_kwargs.get("enable_thinking") is False
    )
    if explicitly_disabled:
        return

    sanitized.pop("tool_choice", None)
    logger.debug(
        "sanitize_model_request_kwargs: dropped tool_choice "
        "(DeepSeek thinking mode does not support it)",
        session_id="NO_SESSION",
    )


def _deepseek_thinking_enabled(request_kwargs: Mapping[str, Any]) -> bool:
    extra_body = request_kwargs.get("extra_body")
    extra_body = extra_body if isinstance(extra_body, Mapping) else {}
    thinking = extra_body.get("thinking")
    thinking_type = (
        str(thinking.get("type") or "").strip().lower()
        if isinstance(thinking, Mapping)
        else ""
    )
    if thinking_type == "disabled":
        return False
    if extra_body.get("enable_thinking") is False:
        return False
    template_kwargs = extra_body.get("chat_template_kwargs")
    if (
        isinstance(template_kwargs, Mapping)
        and template_kwargs.get("enable_thinking") is False
    ):
        return False
    # DeepSeek V4's first-party Chat Completions endpoint defaults to thinking.
    return True


def sanitize_deepseek_tool_history(
    messages: Any,
    *,
    request_kwargs: Mapping[str, Any],
    model: Optional[str],
    client: Any = None,
    model_config: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Return a valid first-party DeepSeek thinking-mode history view.

    A historical assistant tool call without its original ``reasoning_content``
    cannot be faithfully replayed. Remove that assistant/tool pair from the
    outbound view instead of inventing reasoning; never mutate the durable input.
    """
    if not _uses_deepseek_native_protocol(
        model, client=client, model_config=model_config
    ) or not _deepseek_thinking_enabled(request_kwargs):
        return messages
    if not isinstance(messages, Sequence) or isinstance(
        messages, (str, bytes, bytearray)
    ):
        return messages

    missing_tool_call_ids: set[str] = set()
    missing_assistant_indices: set[int] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            continue
        missing_assistant_indices.add(index)
        for tool_call in message.get("tool_calls") or []:
            if isinstance(tool_call, Mapping) and tool_call.get("id"):
                missing_tool_call_ids.add(str(tool_call["id"]))

    changed = False
    filtered: list[Any] = []
    for index, message in enumerate(messages):
        if index in missing_assistant_indices:
            changed = True
            continue
        if isinstance(message, Mapping):
            if (
                message.get("role") == "tool"
                and str(message.get("tool_call_id") or "")
                in missing_tool_call_ids
            ):
                changed = True
                continue
            if message.get("role") == "assistant" and message.get("tool_calls"):
                message_copy = dict(message)
                if message_copy.get("content") is None:
                    message_copy["content"] = ""
                    changed = True
                filtered.append(message_copy)
                continue
        filtered.append(message)

    if not changed:
        return messages
    logger.warning(
        "DeepSeek Chat Completions history sanitized: "
        f"dropped_assistant_turns={len(missing_assistant_indices)}, "
        f"dropped_tool_results={len(missing_tool_call_ids)}",
        session_id="NO_SESSION",
    )
    return filtered


def _drop_sampling_params_for_reasoning_models(
    sanitized: Dict[str, Any],
    model: Optional[str],
) -> None:
    """
    OpenAI / Azure reasoning（o1/o3/o4/gpt-5*）：自定义 temperature 等采样参数常返回
    unsupported_value（仅允许默认值，如 temperature=1）。与是否带 reasoning_effort 无关。
    """
    if not model or not _is_openai_reasoning_model_name(model):
        return
    dropped = []
    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
        if key in sanitized:
            sanitized.pop(key, None)
            dropped.append(key)
    if dropped:
        logger.debug(
            f"sanitize_model_request_kwargs: dropped {dropped} "
            f"(OpenAI reasoning model {model!r} only supports default sampling)",
            session_id="NO_SESSION",
        )


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

    当请求携带 ``tools`` 时，从 ``extra_body`` 移除 ``reasoning_effort``，
    避免部分 OpenAI 推理模型在 chat/completions 上报错。

    对 OpenAI/Azure reasoning 模型（o1/o3/o4/gpt-5*），移除 ``temperature`` 等采样参数
    （这类模型通常只接受默认采样值）。
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
    structured_support = get_structured_output_support(
        client=client, model_config=model_config
    )
    if structured_support is False:
        sanitized.pop("response_format", None)
    _drop_reasoning_effort_when_tools_present(sanitized, resolved_model)
    _drop_tool_choice_for_deepseek_thinking(
        sanitized,
        resolved_model,
        client=client,
        model_config=model_config,
    )
    if "messages" in sanitized:
        sanitized["messages"] = sanitize_deepseek_tool_history(
            sanitized["messages"],
            request_kwargs=sanitized,
            model=resolved_model,
            client=client,
            model_config=model_config,
        )
    _drop_sampling_params_for_reasoning_models(sanitized, resolved_model)
    return sanitized


def is_unsupported_input_format_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "unsupported input format" in error_text
        or "unsupported_input_format" in error_text
        or ("invalidparameter" in error_text and "input format" in error_text)
    )


def _unknown_parameter_name(exc: Exception) -> Optional[str]:
    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            code = str(error.get("code") or "").lower()
            param = error.get("param")
            message = str(error.get("message") or "")
            if code == "unknown_parameter" and isinstance(param, str) and param:
                return param
            match = re.search(r"Unknown parameter:\s*'([^']+)'", message)
            if match:
                return match.group(1)
    param = getattr(exc, "param", None)
    if isinstance(param, str) and param:
        error_text = str(exc).lower()
        if "unknown parameter" in error_text or "unknown_parameter" in error_text:
            return param
    match = re.search(r"Unknown parameter:\s*'([^']+)'", str(exc))
    if match:
        return match.group(1)
    return None


def _drop_unknown_request_parameter(request_kwargs: Dict[str, Any], param: str) -> bool:
    if not param:
        return False
    candidates = [param, param.split(".")[-1]]
    for key in candidates:
        if key in request_kwargs:
            request_kwargs.pop(key, None)
            return True
    extra_body = request_kwargs.get("extra_body")
    if isinstance(extra_body, dict):
        for key in candidates:
            if key in extra_body:
                request_kwargs["extra_body"] = {
                    k: v for k, v in extra_body.items() if k != key
                }
                return True
    return False


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
            if any(
                token in key_str.lower()
                for token in ("key", "token", "secret", "password", "authorization")
            ):
                result[key_str] = "<redacted>"
            else:
                result[key_str] = _sanitize_for_log(
                    item, max_depth=max_depth - 1, max_items=max_items
                )
        if len(items) > max_items:
            result["..."] = f"+{len(items) - max_items} more"
        return result

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
        result = [
            _sanitize_for_log(item, max_depth=max_depth - 1, max_items=max_items)
            for item in items[:max_items]
        ]
        if len(items) > max_items:
            result.append(f"... +{len(items) - max_items} more")
        return result

    return f"<{type(value).__name__}>"


def summarize_chat_completion_messages(messages: Any) -> Any:
    if not isinstance(messages, Sequence) or isinstance(
        messages, (str, bytes, bytearray)
    ):
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
            elif isinstance(content, Sequence) and not isinstance(
                content, (str, bytes, bytearray)
            ):
                item["content_type"] = "list"
                item["content_len"] = len(content)
                item["content_preview"] = _sanitize_for_log(content, max_depth=1)
            else:
                item["content_type"] = type(content).__name__

            if message.get("tool_calls") is not None:
                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, Sequence) and not isinstance(
                    tool_calls, (str, bytes, bytearray)
                ):
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
    summary: Dict[str, Any] = {
        "model": model,
        "request_kwargs": _sanitize_for_log(dict(request_kwargs)),
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

    model = normalize_chat_completions_model(
        model,
        client=client,
        model_config=model_config,
    )

    request_kwargs = sanitize_model_request_kwargs(
        request_kwargs,
        client=client,
        model_config=model_config,
        model=model,
    )
    messages = sanitize_deepseek_tool_history(
        messages,
        request_kwargs=request_kwargs,
        model=model,
        client=client,
        model_config=model_config,
    )
    if get_multimodal_support(client=client, model_config=model_config) is False:
        messages, downgraded_images = downgrade_image_url_parts_for_text_only_model(
            messages
        )
        if downgraded_images:
            logger.info(
                "模型不支持多模态，已从 LLM 请求中移除 image_url 输入: "
                f"count={downgraded_images}, model={model}",
                session_id="NO_SESSION",
            )

    unknown_parameter_retry_count = 0
    structured_output_fallback_used = False
    while True:
        try:
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                **request_kwargs,
            )
        except APIError as exc:
            if (
                response_format is not None
                and not structured_output_fallback_used
                and "response_format" in request_kwargs
                and is_unsupported_input_format_error(exc)
            ):
                structured_output_fallback_used = True
                request_kwargs = dict(request_kwargs)
                request_kwargs.pop("response_format", None)
                logger.warning(
                    "模型后端不支持 structured output，自动移除 response_format 后重试: "
                    f"model={model}, details={format_api_error_details(exc)}",
                    session_id="NO_SESSION",
                )
                continue

            unknown_param = _unknown_parameter_name(exc)
            if unknown_param and unknown_parameter_retry_count < 5:
                retry_kwargs = dict(request_kwargs)
                if _drop_unknown_request_parameter(retry_kwargs, unknown_param):
                    unknown_parameter_retry_count += 1
                    request_kwargs = retry_kwargs
                    logger.warning(
                        "模型后端不支持请求参数，已移除后重试: "
                        f"model={model}, param={unknown_param}, "
                        f"details={format_api_error_details(exc)}",
                        session_id="NO_SESSION",
                    )
                    continue
            raise
