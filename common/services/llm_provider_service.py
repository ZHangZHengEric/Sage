import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from common.models.llm_provider import LLMProvider, LLMProviderDao
from common.schemas.base import LLMProviderCreate, LLMProviderUpdate
from sagents.llm import probe_connection, probe_llm_capabilities, probe_multimodal, probe_structured_output


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
    await probe_connection(api_key, data.base_url, data.model)


async def verify_multimodal(data: LLMProviderCreate) -> Dict[str, Any]:
    api_key = data.api_keys[0] if data.api_keys else None
    if not api_key:
        raise ValueError("API Key is required")
    result = await probe_multimodal(api_key, data.base_url, data.model)
    return {
        "supports_multimodal": bool(result.get("supported")),
        "response": result.get("response"),
        "recognized": bool(result.get("recognized")),
    }


async def verify_structured_output(data: LLMProviderCreate) -> Dict[str, Any]:
    api_key = data.api_keys[0] if data.api_keys else None
    if not api_key:
        raise ValueError("API Key is required")
    result = await probe_structured_output(api_key, data.base_url, data.model)
    return {
        "supports_structured_output": bool(result.get("supported")),
        "response": result.get("response"),
        "error": result.get("error"),
    }


async def verify_capabilities(data: LLMProviderCreate) -> Dict[str, Any]:
    api_key = data.api_keys[0] if data.api_keys else None
    if not api_key:
        raise ValueError("API Key is required")
    return await probe_llm_capabilities(api_key, data.base_url, data.model)


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
        supports_structured_output=data.supports_structured_output,
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
    if data.supports_structured_output is not None:
        provider.supports_structured_output = data.supports_structured_output
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
