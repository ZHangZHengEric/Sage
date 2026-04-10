import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI

from common.models.llm_provider import LLMProvider, LLMProviderDao
from common.schemas.base import LLMProviderCreate, LLMProviderUpdate

_TEST_IMAGE_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"
_COLOR_KEYWORDS = ["red", "红色", "红", "赤", "绯", "朱", "丹", "绛"]


def _is_openai_reasoning_model(model_name: str) -> bool:
    """判断是否为 OpenAI 推理模型"""
    return (
        model_name.startswith("o3-") or
        model_name.startswith("o1-") or
        "gpt" in model_name.lower() or
        "gpt-5.1" in model_name.lower()
    )


def _build_thinking_disabled_extra_body(model_name: str) -> Dict[str, Any]:
    """
    构建用于关闭思考模式的 extra_body 参数

    Args:
        model_name: 模型名称

    Returns:
        Dict[str, Any]: extra_body 参数
    """
    extra_body: Dict[str, Any] = {}

    if _is_openai_reasoning_model(model_name):
        # OpenAI 推理模型使用 reasoning_effort 参数
        # low = 最小化推理
        extra_body["reasoning_effort"] = "low"
    else:
        # 其他模型（如 Qwen3、DeepSeek 等）使用 enable_thinking/thinking 参数
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        extra_body["enable_thinking"] = False
        extra_body["thinking"] = {"type": "disabled"}

    return extra_body


def _normalize_base_url(base_url: Optional[str]) -> Optional[str]:
    return base_url.rstrip("/") if base_url else base_url


def _build_provider_name(model: str, normalized_base_url: Optional[str], name: Optional[str] = None) -> str:
    if name:
        return name
    base = (normalized_base_url or "").replace("https://", "").replace("http://", "").split("/")[0]
    return f"{model}@{base}"


async def verify_provider(data: LLMProviderCreate) -> None:
    api_key = data.api_keys[0] if data.api_keys else None
    if not api_key:
        raise ValueError("API Key is required")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=data.base_url,
        timeout=10.0,
    )

    # 构建 extra_body 以关闭思考模式
    extra_body = _build_thinking_disabled_extra_body(data.model)

    await client.chat.completions.create(
        model=data.model,
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=5,
        extra_body=extra_body,
    )


async def verify_multimodal(data: LLMProviderCreate) -> Dict[str, Any]:
    api_key = data.api_keys[0] if data.api_keys else None
    if not api_key:
        raise ValueError("API Key is required")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=data.base_url,
        timeout=30.0,
    )

    # 构建 extra_body 以关闭思考模式
    extra_body = _build_thinking_disabled_extra_body(data.model)

    response = await client.chat.completions.create(
        model=data.model,
        messages=[
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
        ],
        max_tokens=50,
        temperature=0.1,
        extra_body=extra_body,
    )

    content = response.choices[0].message.content.lower() if response.choices[0].message.content else ""
    logger.info(f"Multimodal verification response: {content}")
    recognized = any(keyword in content for keyword in _COLOR_KEYWORDS)
    return {
        "supports_multimodal": True,
        "response": content,
        "recognized": recognized,
    }


async def list_providers(user_id: str) -> List[Dict[str, Any]]:
    providers = await LLMProviderDao().get_list(user_id=user_id)
    return [provider.to_dict() for provider in providers]


async def create_provider(
    data: LLMProviderCreate,
    *,
    user_id: str,
) -> str:
    dao = LLMProviderDao()
    normalized_base_url = _normalize_base_url(data.base_url)
    existing_providers = await dao.get_by_config(
        base_url=normalized_base_url or "",
        model=data.model,
        user_id=user_id,
    )
    logger.info(
        f"[LLMProvider] Checking existing providers for base_url={normalized_base_url}, "
        f"model={data.model}, user_id={user_id}, found {len(existing_providers)} candidates"
    )
    logger.info(f"[LLMProvider] Request api_keys: {data.api_keys}")

    for provider in existing_providers:
        logger.info(f"[LLMProvider] Comparing with provider {provider.id}: api_keys={provider.api_keys}")
        if sorted(provider.api_keys) == sorted(data.api_keys):
            logger.info(f"[LLMProvider] Found matching provider: {provider.id}")
            return provider.id

    provider_id = str(uuid.uuid4())
    provider = LLMProvider(
        id=provider_id,
        name=_build_provider_name(data.model, normalized_base_url, data.name),
        base_url=normalized_base_url or "",
        api_keys=data.api_keys,
        model=data.model,
        max_tokens=data.max_tokens,
        temperature=data.temperature,
        top_p=data.top_p,
        presence_penalty=data.presence_penalty,
        max_model_len=data.max_model_len,
        supports_multimodal=data.supports_multimodal,
        is_default=bool(data.is_default),
        user_id=user_id,
    )
    await dao.save(provider)
    return provider_id


async def update_provider(
    provider_id: str,
    data: LLMProviderUpdate,
    *,
    user_id: str,
    allow_system_default_update: bool,
) -> LLMProvider:
    dao = LLMProviderDao()
    provider = await dao.get_by_id(provider_id)
    if not provider:
        raise ValueError("Provider not found")
    if provider.user_id and provider.user_id != user_id:
        raise PermissionError("Permission denied")
    if not allow_system_default_update and not provider.user_id:
        raise PermissionError("Cannot modify system default provider")

    if data.name is not None:
        provider.name = data.name
    if data.base_url is not None:
        provider.base_url = data.base_url
    if data.api_keys is not None:
        provider.api_keys = data.api_keys
    if data.model is not None:
        provider.model = data.model
    if data.max_tokens is not None:
        provider.max_tokens = data.max_tokens
    if data.temperature is not None:
        provider.temperature = data.temperature
    if data.top_p is not None:
        provider.top_p = data.top_p
    if data.presence_penalty is not None:
        provider.presence_penalty = data.presence_penalty
    if data.max_model_len is not None:
        provider.max_model_len = data.max_model_len
    if data.supports_multimodal is not None:
        provider.supports_multimodal = data.supports_multimodal
    if data.is_default is not None:
        provider.is_default = data.is_default

    await dao.save(provider)
    return provider


async def delete_provider(provider_id: str, *, user_id: str) -> None:
    dao = LLMProviderDao()
    provider = await dao.get_by_id(provider_id)
    if not provider:
        raise ValueError("Provider not found")
    if provider.is_default:
        raise ValueError("Cannot delete default provider")
    if provider.user_id and provider.user_id != user_id:
        raise PermissionError("Permission denied")
    await dao.delete_by_id(provider_id)
