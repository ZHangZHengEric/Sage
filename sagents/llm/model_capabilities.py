from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from loguru import logger
from openai import AsyncOpenAI
from sagents.utils.llm_request_utils import summarize_chat_completion_request
from sagents.utils.prompt_caching import add_cache_control_to_messages

_TEST_IMAGE_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"
_COLOR_KEYWORDS = ["red", "红色", "红", "赤", "绯", "朱", "丹", "绛"]


def _is_openai_reasoning_model(model_name: str) -> bool:
    model = (model_name or "").lower()
    return model.startswith("o3-") or model.startswith("o1-") or "gpt" in model or "gpt-5.1" in model


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
        request_kwargs = {"max_tokens": 5}
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
        request_kwargs = {"max_tokens": 50, "temperature": 0.1}
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
            request_kwargs = {
                "response_format": {"type": "json_object"},
                "max_tokens": 20,
                "temperature": 0.0,
                "stream": True,
                "extra_body": _build_probe_extra_body(model),
            }
            logger.info(
                f"[LLM Capability Probe] structured_output request | summary={summarize_chat_completion_request(model=model, messages=request_messages, request_kwargs=request_kwargs)}"
            )
            stream = await client.chat.completions.create(
                model=model,
                messages=request_messages,
                response_format=request_kwargs["response_format"],
                max_tokens=request_kwargs["max_tokens"],
                temperature=request_kwargs["temperature"],
                stream=request_kwargs["stream"],
                extra_body=request_kwargs["extra_body"],
            )
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
    multimodal = await probe_multimodal(api_key, base_url, model)
    structured_output = await probe_structured_output(api_key, base_url, model)

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
