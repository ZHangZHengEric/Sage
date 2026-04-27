from __future__ import annotations

import json
from typing import Any, Awaitable, Dict, Optional

import httpx
from loguru import logger
from openai import AsyncOpenAI
from sagents.utils.llm_request_utils import (
    summarize_chat_completion_request,
    uses_max_completion_tokens,
)
from sagents.utils.prompt_caching import add_cache_control_to_messages

_TEST_IMAGE_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"
_COLOR_KEYWORDS = ["red", "红色", "红", "赤", "绯", "朱", "丹", "绛"]


_REASONING_MODEL_PREFIXES: tuple[str, ...] = (
    "o1-",
    "o3-",
    "o4-",
    "gpt-5",  # gpt-5, gpt-5-, gpt-5.x, gpt-5-mini 等 reasoning 系
)
_REASONING_MODEL_EXACT: frozenset[str] = frozenset({"o1", "o3", "o4"})


_VALID_REASONING_EFFORTS: frozenset[str] = frozenset({"minimal", "low", "medium", "high"})


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


def resolve_reasoning_effort(
    enable_thinking: bool,
    env_value: Optional[str] = None,
    default_off: str = "low",
) -> str:
    """根据是否启用思考与环境变量解析最终的 ``reasoning_effort``。

    - ``enable_thinking=True`` → ``"medium"``
    - ``enable_thinking=False`` → ``env_value`` 优先（小写），无效或为空时回退 ``default_off``
    - 合法值：minimal / low / medium / high
    """
    if enable_thinking:
        return "medium"
    if env_value is None:
        return default_off
    candidate = env_value.strip().lower()
    if candidate and candidate in _VALID_REASONING_EFFORTS:
        return candidate
    return default_off


def _is_openai_reasoning_model(model_name: str) -> bool:
    """旧名兼容的 thin wrapper。"""
    return is_openai_reasoning_model(model_name)


def _build_client(api_key: str, base_url: str, timeout: float) -> AsyncOpenAI:
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        trust_env=False,
    )
    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        http_client=http_client,
    )


def _build_probe_extra_body(model: str) -> Dict[str, Any]:
    extra_body: Dict[str, Any] = {
        "top_k": 20,
        "_step_name": "capability_probe_structured_output",
    }

    if _is_openai_reasoning_model(model):
        extra_body["reasoning_effort"] = "low"
    else:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        extra_body["enable_thinking"] = False
        extra_body["thinking"] = {"type": "disabled"}

    return extra_body


async def _probe_optional_capability(capability: str, probe_coro: Awaitable[Dict[str, Any]]) -> Dict[str, Any]:
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
        "This request is intentionally shaped like the runtime LLM call, including cache control.\n"
        "Do not explain anything outside the JSON object."
    )
    # Make the system message long enough to exercise the same cache_control path as runtime.
    system_text = system_text + "\n" + ("Capability probe context. " * 30)
    messages = [
        {"role": "system", "content": system_text},
        {
            "role": "user",
            "content": "Return a JSON object with a single key named ok whose value is true.",
        },
    ]
    add_cache_control_to_messages(messages)
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
        response = await client.chat.completions.create(
            model=model,
            messages=request_messages,
            **request_kwargs,
        )

        content = response.choices[0].message.content.lower() if response.choices[0].message.content else ""
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


async def probe_structured_output(api_key: str, base_url: str, model: str) -> Dict[str, Any]:
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
                "extra_body": _build_probe_extra_body(model),
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


async def probe_llm_capabilities(api_key: str, base_url: str, model: str) -> Dict[str, Any]:
    logger.info(
        f"[LLM Capability Probe] start | model={model} | base_url={base_url}"
    )
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
