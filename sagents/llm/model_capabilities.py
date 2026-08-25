from __future__ import annotations

import json
from typing import Any, Awaitable, Dict, Mapping, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger
from openai import AsyncOpenAI
from sagents.utils.llm_request_utils import (
    summarize_chat_completion_request,
    uses_max_completion_tokens,
)

_TEST_IMAGE_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"
_COLOR_KEYWORDS = ["red", "红色", "红", "赤", "绯", "朱", "丹", "绛"]


_REASONING_MODEL_PREFIXES: tuple[str, ...] = (
    "o1-",
    "o3-",
    "o4-",
    "gpt-5",  # gpt-5, gpt-5-, gpt-5.x, gpt-5-mini 等 reasoning 系
)
_REASONING_MODEL_EXACT: frozenset[str] = frozenset({"o1", "o3", "o4"})


_VALID_REASONING_EFFORTS: frozenset[str] = frozenset(
    {"minimal", "low", "medium", "high", "xhigh"}
)
_VALID_THINKING_LEVELS: frozenset[str] = _VALID_REASONING_EFFORTS | {"max"}


def is_openai_reasoning_model(model_name: str) -> bool:
    """是否为 OpenAI / 兼容三方的 reasoning 系列模型。

    判定基于显式前缀/精确名单，避免把 ``gpt-4o``/``gpt-4-turbo``/``gpt-3.5`` 这类
    非 reasoning 模型误判进 reasoning 路径。
    """
    if not model_name:
        return False
    name = model_name.strip().lower()
    if not name:
        return False
    if name in _REASONING_MODEL_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in _REASONING_MODEL_PREFIXES)


def is_deepseek_model(model_name: str) -> bool:
    """Return whether the provider-facing model slug is a DeepSeek model."""
    if not model_name:
        return False
    name = model_name.strip().lower()
    return (
        name.startswith("deepseek-")
        or name.startswith("deepseek/")
        or "/deepseek-" in name
    )


def is_official_deepseek_endpoint(base_url: Optional[str]) -> bool:
    """Return whether ``base_url`` is DeepSeek's first-party API endpoint."""
    if not base_url:
        return False
    raw = str(base_url).strip()
    if not raw:
        return False
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower() == "api.deepseek.com"


def uses_deepseek_native_protocol(
    model_name: str, base_url: Optional[str]
) -> bool:
    """Whether a request should use DeepSeek's native Chat Completions contract.

    Third-party OpenAI-compatible endpoints may expose ``deepseek-*`` model names,
    but their reasoning/tool-call replay contracts are not guaranteed to match the
    first-party API.
    """
    return is_deepseek_model(model_name) and is_official_deepseek_endpoint(base_url)


def is_minimax_model(model_name: str) -> bool:
    """Return whether the provider-facing model slug is a MiniMax model."""
    return str(model_name or "").strip().lower().startswith("minimax-")


def is_official_minimax_endpoint(base_url: Optional[str]) -> bool:
    """Return whether ``base_url`` is a MiniMax first-party API endpoint."""
    hostname = _endpoint_hostname(base_url)
    return hostname in {"api.minimaxi.com", "api.minimax.io"}


def uses_minimax_native_protocol(
    model_name: str, base_url: Optional[str]
) -> bool:
    """Whether the request should use MiniMax's native OpenAI extensions."""
    return is_minimax_model(model_name) and is_official_minimax_endpoint(base_url)


def _endpoint_hostname(base_url: Optional[str]) -> str:
    if not base_url:
        return ""
    raw = str(base_url).strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower()


def _is_aliyun_model_studio_endpoint(base_url: Optional[str]) -> bool:
    hostname = _endpoint_hostname(base_url)
    return hostname == "dashscope.aliyuncs.com" or hostname.endswith(
        ".dashscope.aliyuncs.com"
    )


def _is_zhipu_endpoint(base_url: Optional[str]) -> bool:
    return _endpoint_hostname(base_url) == "open.bigmodel.cn"


def uses_aliyun_model_studio_protocol(base_url: Optional[str]) -> bool:
    return _is_aliyun_model_studio_endpoint(base_url)


def uses_zhipu_native_protocol(base_url: Optional[str]) -> bool:
    return _is_zhipu_endpoint(base_url)


def get_supported_thinking_levels(
    model_name: str,
    base_url: Optional[str] = None,
) -> tuple[str, ...]:
    """Return the discrete effort values supported by this model/provider pair.

    The frontend vocabulary stays fixed. This native capability list is used at
    the request boundary to map that vocabulary onto provider-specific values.
    An empty tuple means Sage only knows how to toggle thinking for that model.
    """
    name = str(model_name or "").strip().lower()
    if not name:
        return ()
    if uses_deepseek_native_protocol(name, base_url):
        return ("low", "high", "max")
    if is_openai_reasoning_model(name):
        if name.startswith("gpt-5.6"):
            return ("low", "medium", "high", "xhigh", "max")
        if name.startswith(
            ("gpt-5.2", "gpt-5.3", "gpt-5.4", "gpt-5.5")
        ):
            return ("low", "medium", "high", "xhigh")
        if name.startswith("gpt-5.1"):
            return ("low", "medium", "high")
        if name.startswith("gpt-5"):
            return ("minimal", "low", "medium", "high")
        return ("low", "medium", "high")
    if _is_aliyun_model_studio_endpoint(base_url):
        if name.startswith("deepseek-v4-"):
            return ("low", "high", "max")
        if name.startswith("qwen3.8-max-preview"):
            return ("low", "medium", "xhigh")
        if name.startswith(("glm-5", "glm-5.1", "glm-5.2")):
            return ("high", "max")
        if name in {"kimi/kimi-k3", "kimi-k3"}:
            return ("max",)
    if _is_zhipu_endpoint(base_url) and name.startswith("glm-5.2"):
        return ("high", "max")
    return ()


def get_default_thinking_level(
    model_name: str,
    base_url: Optional[str] = None,
) -> Optional[str]:
    """Map the frontend's default ``medium`` level to the model's native value."""
    levels = get_supported_thinking_levels(model_name, base_url)
    if not levels:
        return None
    return normalize_reasoning_effort(
        model_name,
        "medium",
        base_url=base_url,
    )


def normalize_reasoning_effort(
    model_name: str,
    thinking_level: str,
    *,
    base_url: Optional[str] = None,
) -> str:
    """Normalize the shared level vocabulary to a provider-supported value."""
    level = str(thinking_level or "").strip().lower()
    if level not in _VALID_THINKING_LEVELS:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")
    supported = get_supported_thinking_levels(model_name, base_url)
    if not supported or level in supported:
        return level
    effort_rank = {
        "minimal": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "xhigh": 4,
        "max": 5,
    }
    requested_rank = effort_rank[level]
    for candidate in supported:
        if effort_rank[candidate] >= requested_rank:
            return candidate
    return supported[-1]


def resolve_reasoning_effort(
    enable_thinking: bool,
    env_value: Optional[str] = None,
    default_off: str = "medium",
) -> str:
    """根据是否启用思考与环境变量解析最终的 ``reasoning_effort``。

    - ``enable_thinking=True`` → ``"medium"``
    - ``enable_thinking=False`` → ``env_value`` 优先（小写），无效或为空时回退 ``default_off``
    - 合法值：minimal / low / medium / high / xhigh
    """
    if enable_thinking:
        return "medium"
    if env_value is None:
        return default_off
    candidate = env_value.strip().lower()
    if candidate and candidate in _VALID_REASONING_EFFORTS:
        return candidate
    return default_off


def build_llm_extra_body(
    model_name: str,
    *,
    base_url: Optional[str] = None,
    enable_thinking: bool = False,
    thinking_level: Optional[str] = None,
    step_name: Optional[str] = None,
    reasoning_effort_off_env: Optional[str] = None,
    default_off: str = "medium",
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """构建与主 Agent 一致的 chat.completions ``extra_body``。

    - OpenAI reasoning（o1/o3/o4/gpt-5*）：设置 ``reasoning_effort``
    - 其他模型：设置 ``enable_thinking`` / ``thinking`` / ``chat_template_kwargs``
    - ``extra``：调用方附加字段（如能力探测的 ``top_k``）
    """
    extra_body: Dict[str, Any] = {}
    if step_name:
        extra_body["_step_name"] = step_name

    if thinking_level:
        enable_thinking = True

    supported_thinking_levels = get_supported_thinking_levels(
        model_name, base_url
    )
    if is_openai_reasoning_model(model_name):
        extra_body["reasoning_effort"] = (
            normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
            if thinking_level
            else resolve_reasoning_effort(
                enable_thinking=enable_thinking,
                env_value=reasoning_effort_off_env,
                default_off=default_off,
            )
        )
    elif uses_minimax_native_protocol(model_name, base_url):
        # MiniMax's OpenAI-compatible API otherwise embeds thinking inside
        # content as <think>...</think>. Split it into structured fields so Sage
        # can keep private reasoning separate from the visible answer.
        extra_body["reasoning_split"] = True
        if str(model_name or "").strip().lower().startswith("minimax-m3"):
            extra_body["thinking"] = {
                "type": "adaptive" if enable_thinking else "disabled"
            }
    elif uses_deepseek_native_protocol(model_name, base_url):
        # The first-party Chat Completions API only documents these native
        # fields. Do not mix in local-engine compatibility switches such as
        # enable_thinking/chat_template_kwargs.
        extra_body["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
        if thinking_level:
            extra_body["reasoning_effort"] = normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
    elif uses_aliyun_model_studio_protocol(base_url):
        extra_body["enable_thinking"] = enable_thinking
        if thinking_level and supported_thinking_levels:
            extra_body["reasoning_effort"] = normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
    elif uses_zhipu_native_protocol(base_url):
        extra_body["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
        if thinking_level and supported_thinking_levels:
            extra_body["reasoning_effort"] = normalize_reasoning_effort(
                model_name, thinking_level, base_url=base_url
            )
    else:
        extra_body["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
        extra_body["enable_thinking"] = enable_thinking
        extra_body["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
    if extra:
        extra_body.update(extra)
    return extra_body


def _build_client(api_key: str, base_url: str, timeout: float) -> AsyncOpenAI:
    http_client = httpx.AsyncClient(
        headers={"Accept-Encoding": "identity"},
        timeout=httpx.Timeout(timeout),
        trust_env=False,
    )
    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        http_client=http_client,
    )


async def _probe_optional_capability(
    capability: str, probe_coro: Awaitable[Dict[str, Any]]
) -> Dict[str, Any]:
    try:
        return await probe_coro
    except Exception as exc:
        logger.info(
            f"[LLM Capability Probe] {capability} optional probe failed | error={exc}"
        )
        return {
            "supported": False,
            "error": str(exc),
        }


def _build_probe_messages() -> list[Dict[str, Any]]:
    system_text = (
        "You are a model capability probe running inside Sage.\n"
        "You must follow the response format strictly.\n"
        "This request is intentionally shaped like the runtime LLM call.\n"
        "Do not explain anything outside the JSON object."
    )
    messages = [
        {"role": "system", "content": system_text},
        {
            "role": "user",
            "content": "Return a JSON object with a single key named ok whose value is true.",
        },
    ]
    return messages


async def probe_connection(api_key: str, base_url: str, model: str) -> Dict[str, Any]:
    logger.info(
        f"[LLM Capability Probe] connection | model={model} | base_url={base_url}"
    )
    client = _build_client(api_key, base_url, timeout=10.0)
    try:
        request_kwargs: Dict[str, Any] = (
            {"max_completion_tokens": 5}
            if uses_max_completion_tokens(model)
            else {"max_tokens": 5}
        )
        logger.info(
            f"[LLM Capability Probe] connection request | summary={summarize_chat_completion_request(model=model, messages=[{'role': 'user', 'content': 'Hi'}], request_kwargs=request_kwargs)}"
        )
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            **request_kwargs,
        )
        content = response.choices[0].message.content if response.choices else None
        logger.info(
            f"[LLM Capability Probe] connection success | model={model} | response={content!r}"
        )
        return {
            "supported": True,
            "response": content,
        }
    finally:
        await client.close()


async def probe_multimodal(api_key: str, base_url: str, model: str) -> Dict[str, Any]:
    logger.info(
        f"[LLM Capability Probe] multimodal | model={model} | base_url={base_url} | test=image_color"
    )
    client = _build_client(api_key, base_url, timeout=30.0)
    try:
        request_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _TEST_IMAGE_URL}},
                    {
                        "type": "text",
                        "text": "What color is this image? Please answer with just the color name.",
                    },
                ],
            }
        ]
        request_kwargs = {"temperature": 0.1}
        if uses_max_completion_tokens(model):
            request_kwargs["max_completion_tokens"] = 50
        else:
            request_kwargs["max_tokens"] = 50
        logger.info(
            f"[LLM Capability Probe] multimodal request | summary={summarize_chat_completion_request(model=model, messages=request_messages, request_kwargs=request_kwargs)}"
        )
        response = await client.chat.completions.create(  # pyright: ignore[reportCallIssue]
            model=model,
            messages=request_messages,  # pyright: ignore[reportArgumentType]
            **request_kwargs,  # pyright: ignore[reportArgumentType]
        )

        content = (
            response.choices[0].message.content.lower()
            if response.choices[0].message.content
            else ""
        )
        recognized = any(keyword in content for keyword in _COLOR_KEYWORDS)
        supported = recognized
        logger.info(
            f"[LLM Capability Probe] multimodal result | model={model} | supported={supported} | recognized={recognized} | response={content!r}"
        )
        return {
            "supported": supported,
            "recognized": recognized,
            "response": content,
        }
    finally:
        await client.close()


async def probe_structured_output(
    api_key: str, base_url: str, model: str
) -> Dict[str, Any]:
    logger.info(
        f"[LLM Capability Probe] structured_output | model={model} | base_url={base_url} | test=response_format=json_object"
    )
    client = _build_client(api_key, base_url, timeout=20.0)

    try:
        try:
            request_messages = _build_probe_messages()
            token_kw: Dict[str, Any] = (
                {"max_completion_tokens": 20}
                if uses_max_completion_tokens(model)
                else {"max_tokens": 20}
            )
            request_kwargs = {
                "response_format": {"type": "json_object"},
                **token_kw,
                "temperature": 0.0,
                "stream": True,
                # 探测保留历史 top_k；OpenAI 兼容路径由上层 sanitize/fallback 处理。
                "extra_body": build_llm_extra_body(
                    model,
                    enable_thinking=False,
                    step_name="capability_probe_structured_output",
                    extra={"top_k": 20},
                ),
            }
            logger.info(
                f"[LLM Capability Probe] structured_output request | summary={summarize_chat_completion_request(model=model, messages=request_messages, request_kwargs=request_kwargs)}"
            )
            create_kw: Dict[str, Any] = {
                "model": model,
                "messages": request_messages,
                "response_format": request_kwargs["response_format"],
                "temperature": request_kwargs["temperature"],
                "stream": request_kwargs["stream"],
                "extra_body": request_kwargs["extra_body"],
            }
            create_kw.update(token_kw)
            stream = await client.chat.completions.create(**create_kw)
            content_chunks: list[str] = []
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    content_chunks.append(delta.content)
            content = "".join(content_chunks).strip() or None
            parsed: Any = None
            supported = False
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except Exception as parse_exc:
                    logger.info(
                        f"[LLM Capability Probe] structured_output parse failed | model={model} | error={parse_exc} | response={content!r}"
                    )
                else:
                    supported = isinstance(parsed, dict) and "ok" in parsed
            else:
                logger.info(
                    f"[LLM Capability Probe] structured_output invalid type | model={model} | type={type(content).__name__} | response={content!r}"
                )
            logger.info(
                f"[LLM Capability Probe] structured_output result | model={model} | supported={supported} | parsed={parsed!r} | response={content!r}"
            )
            return {
                "supported": supported,
                "response": content,
                "parsed": parsed,
            }
        except Exception as exc:
            logger.info(
                f"[LLM Capability Probe] structured_output failed | model={model} | error={exc}"
            )
            return {
                "supported": False,
                "error": str(exc),
            }
    finally:
        await client.close()


async def probe_llm_capabilities(
    api_key: str, base_url: str, model: str
) -> Dict[str, Any]:
    logger.info(f"[LLM Capability Probe] start | model={model} | base_url={base_url}")
    connection = await probe_connection(api_key, base_url, model)
    multimodal = await _probe_optional_capability(
        "multimodal",
        probe_multimodal(api_key, base_url, model),
    )
    structured_output = await _probe_optional_capability(
        "structured_output",
        probe_structured_output(api_key, base_url, model),
    )

    report = {
        "connection": connection,
        "supports_multimodal": bool(multimodal.get("supported")),
        "supports_structured_output": bool(structured_output.get("supported")),
        "multimodal": multimodal,
        "structured_output": structured_output,
        "model": model,
        "base_url": base_url,
    }
    logger.info(
        f"[LLM Capability Probe] summary | model={model} | supports_multimodal={report['supports_multimodal']} | supports_structured_output={report['supports_structured_output']}"
    )
    return report
