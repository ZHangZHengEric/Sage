import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from common.models.llm_provider import LLMProvider, LLMProviderDao
from common.services.llm_provider_probe_utils import friendly_provider_probe_error
from common.schemas.base import LLMProviderCreate, LLMProviderUpdate
from sagents.llm import probe_connection, probe_llm_capabilities, probe_multimodal, probe_structured_output


def _normalize_base_url(base_url: Optional[str]) -> Optional[str]:
    return base_url.rstrip("/") if base_url else base_url


def _build_provider_name(model: str, normalized_base_url: Optional[str], name: Optional[str] = None) -> str:
    if name:
        return name
    base = (normalized_base_url or "").replace("https://", "").replace("http://", "").split("/")[0]
    return f"{model}@{base}"


def _resolve_api_key(api_keys: Optional[List[str]]) -> str:
    api_key = api_keys[0] if api_keys else None
    if not api_key:
        raise ValueError("API Key is required")
    return api_key


async def _probe_provider_or_raise(*, api_keys: Optional[List[str]], base_url: Optional[str], model: str, action: str) -> None:
    api_key = _resolve_api_key(api_keys)
    try:
        await probe_connection(api_key, base_url or "", model)
    except Exception as exc:
        logger.warning(
            f"[LLMProvider] Probe failed before {action}: base_url={base_url}, model={model}, error={exc}"
        )
        raise ValueError(
            f"Cannot {action}. {friendly_provider_probe_error(exc, subject='Provider')}"
        ) from exc


async def verify_provider(data: LLMProviderCreate) -> None:
    api_key = _resolve_api_key(data.api_keys)
    await probe_connection(api_key, _normalize_base_url(data.base_url) or "", data.model)


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

    await _probe_provider_or_raise(
        api_keys=data.api_keys,
        base_url=normalized_base_url,
        model=data.model,
        action="save provider",
    )

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
    if provider.is_default:
        await dao.clear_default_for_user(user_id=user_id, exclude_provider_id=provider_id)
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

    effective_base_url = _normalize_base_url(data.base_url) if data.base_url is not None else provider.base_url
    effective_api_keys = data.api_keys if data.api_keys is not None else provider.api_keys
    effective_model = data.model if data.model is not None else provider.model

    await _probe_provider_or_raise(
        api_keys=effective_api_keys,
        base_url=effective_base_url,
        model=effective_model,
        action="update provider",
    )

    if data.name is not None:
        provider.name = data.name
    if data.base_url is not None:
        provider.base_url = effective_base_url or ""
    if data.api_keys is not None:
        provider.api_keys = data.api_keys
    if data.model is not None:
        provider.model = data.model
    # 采样参数允许显式置空：使用 model_fields_set 区分"未提供"和"显式 null"，
    # 让用户在前端清空后能真正清掉 DB 中的值，避免下游仍把旧值带进 LLM 请求。
    fields_set = data.model_fields_set
    if "max_tokens" in fields_set:
        provider.max_tokens = data.max_tokens
    if "temperature" in fields_set:
        provider.temperature = data.temperature
    if "top_p" in fields_set:
        provider.top_p = data.top_p
    if "presence_penalty" in fields_set:
        provider.presence_penalty = data.presence_penalty
    if "max_model_len" in fields_set:
        provider.max_model_len = data.max_model_len
    if data.supports_multimodal is not None:
        provider.supports_multimodal = data.supports_multimodal
    if data.supports_structured_output is not None:
        provider.supports_structured_output = data.supports_structured_output
    if data.is_default is not None:
        provider.is_default = data.is_default

    if provider.is_default:
        await dao.clear_default_for_user(user_id=provider.user_id, exclude_provider_id=provider.id)
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
