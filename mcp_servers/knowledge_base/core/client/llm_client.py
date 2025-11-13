"""
大模型api客户端
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from openai import AsyncOpenAI
from config.settings import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
)


async def init_llm_client() -> AsyncOpenAI:

    if LLM_BASE_URL:
        return AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return AsyncOpenAI(api_key=LLM_API_KEY)


async def get_llm_client() -> AsyncOpenAI:
    return await init_llm_client()


async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    client = await get_llm_client()
    m = model or LLM_MODEL
    t = temperature if temperature is not None else LLM_TEMPERATURE
    mt = max_tokens if max_tokens is not None else LLM_MAX_TOKENS
    r = await client.chat.completions.create(
        model=m,
        messages=messages,
        temperature=t,
        max_tokens=mt,
    )
    choice = r.choices[0]
    return {
        "content": choice.message.content,
        "finish_reason": choice.finish_reason,
        "id": r.id,
        "model": r.model,
    }


async def close_llm_client() -> None:
    return None
