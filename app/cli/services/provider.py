from typing import Any, Dict, Optional

from app.cli.services.base import CLIError, sanitize_provider_record, trim_optional_text
from app.cli.services.runtime import get_default_cli_user_id, init_cli_config
from common.services.llm_provider_probe_utils import friendly_provider_probe_error


def _resolve_provider_create_data(
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.schemas.base import LLMProviderCreate

    cfg = init_cli_config(init_logging=False)
    resolved_base_url = trim_optional_text(base_url) or trim_optional_text(cfg.default_llm_api_base_url)
    resolved_api_key = trim_optional_text(api_key) or trim_optional_text(cfg.default_llm_api_key)
    resolved_model = trim_optional_text(model) or trim_optional_text(cfg.default_llm_model_name)

    next_steps = []
    if not resolved_api_key:
        next_steps.append("Pass `--api-key`, or set `SAGE_DEFAULT_LLM_API_KEY` in `~/.sage/.sage_env` or local `.env`.")
    if not resolved_base_url:
        next_steps.append("Pass `--base-url`, or set `SAGE_DEFAULT_LLM_API_BASE_URL` in `~/.sage/.sage_env` or local `.env`.")
    if not resolved_model:
        next_steps.append("Pass `--model`, or set `SAGE_DEFAULT_LLM_MODEL_NAME` in `~/.sage/.sage_env` or local `.env`.")
    if next_steps:
        raise CLIError(
            "Provider configuration is incomplete for create/verify.",
            next_steps=next_steps,
        )

    return {
        "data": LLMProviderCreate(
            name=trim_optional_text(name),
            base_url=resolved_base_url,
            api_keys=[resolved_api_key],
            model=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
            max_model_len=max_model_len,
            supports_multimodal=bool(supports_multimodal),
            supports_structured_output=bool(supports_structured_output),
            is_default=bool(is_default),
        ),
        "sources": {
            "base_url": "arg" if trim_optional_text(base_url) else "default",
            "api_key": "arg" if trim_optional_text(api_key) else "default",
            "model": "arg" if trim_optional_text(model) else "default",
        },
    }


def _build_provider_update_data(
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Any:
    from common.schemas.base import LLMProviderUpdate

    payload: Dict[str, Any] = {}
    if name is not None:
        payload["name"] = trim_optional_text(name)
    if base_url is not None:
        payload["base_url"] = trim_optional_text(base_url)
    if api_key is not None:
        normalized_api_key = trim_optional_text(api_key)
        if not normalized_api_key:
            raise CLIError(
                "Provider API key cannot be empty.",
                next_steps=["Pass a non-empty `--api-key` value."],
            )
        payload["api_keys"] = [normalized_api_key]
    if model is not None:
        payload["model"] = trim_optional_text(model)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty
    if max_model_len is not None:
        payload["max_model_len"] = max_model_len
    if supports_multimodal is not None:
        payload["supports_multimodal"] = supports_multimodal
    if supports_structured_output is not None:
        payload["supports_structured_output"] = supports_structured_output
    if is_default is not None:
        payload["is_default"] = is_default

    if not payload:
        raise CLIError(
            "No provider fields were supplied for update.",
            next_steps=[
                "Pass at least one field such as `--model`, `--base-url`, `--api-key`, or `--name`.",
            ],
        )

    return LLMProviderUpdate(**payload)


async def list_cli_providers(*, user_id: Optional[str] = None) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    providers = await llm_provider_service.list_providers(resolved_user_id)
    sanitized = [sanitize_provider_record(item) for item in providers]
    return {
        "user_id": resolved_user_id,
        "total": len(sanitized),
        "list": sanitized,
    }


async def query_cli_providers(
    *,
    user_id: Optional[str] = None,
    default_only: bool = False,
    model: Optional[str] = None,
    name_contains: Optional[str] = None,
) -> Dict[str, Any]:
    result = await list_cli_providers(user_id=user_id)
    providers = list(result.get("list") or [])

    normalized_model = trim_optional_text(model)
    normalized_name_query = (trim_optional_text(name_contains) or "").lower()

    if default_only:
        providers = [item for item in providers if bool(item.get("is_default"))]
    if normalized_model:
        providers = [item for item in providers if item.get("model") == normalized_model]
    if normalized_name_query:
        providers = [
            item
            for item in providers
            if normalized_name_query in ((item.get("name") or "").lower())
        ]

    return {
        **result,
        "filters": {
            "default_only": default_only,
            "model": normalized_model,
            "name_contains": trim_optional_text(name_contains),
        },
        "total": len(providers),
        "list": providers,
    }


async def inspect_cli_provider(*, provider_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    from common.models.llm_provider import LLMProviderDao

    resolved_user_id = user_id or get_default_cli_user_id()
    provider = await LLMProviderDao().get_by_id(provider_id)
    if not provider:
        raise CLIError(
            f"Provider not found: {provider_id}",
            next_steps=["Run `sage provider list` to inspect visible providers."],
        )
    if provider.user_id and provider.user_id != resolved_user_id:
        raise CLIError(
            f"Provider {provider_id} is not visible to user {resolved_user_id}",
            next_steps=[f"Run `sage provider list --user-id {resolved_user_id}` to inspect visible providers."],
        )
    return {
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "provider": sanitize_provider_record(provider.to_dict()),
    }


async def verify_cli_provider(
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved = _resolve_provider_create_data(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        max_model_len=max_model_len,
        supports_multimodal=supports_multimodal,
        supports_structured_output=supports_structured_output,
        is_default=is_default,
    )
    data = resolved["data"]
    try:
        await llm_provider_service.verify_provider(data)
    except Exception as exc:
        raise CLIError(
            friendly_provider_probe_error(exc, subject="Provider"),
            next_steps=[
                "Check `--api-key`, `--base-url`, and `--model`, then run `sage provider verify` again.",
            ],
        ) from exc
    return {
        "status": "ok",
        "message": "Provider verification succeeded",
        "sources": resolved["sources"],
        "provider": sanitize_provider_record(data.model_dump()),
    }


async def create_cli_provider(
    *,
    user_id: Optional[str] = None,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    resolved = _resolve_provider_create_data(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        max_model_len=max_model_len,
        supports_multimodal=supports_multimodal,
        supports_structured_output=supports_structured_output,
        is_default=is_default,
    )
    provider_id = await llm_provider_service.create_provider(resolved["data"], user_id=resolved_user_id)
    providers = await llm_provider_service.list_providers(resolved_user_id)
    provider = next((item for item in providers if item.get("id") == provider_id), None)
    return {
        "status": "ok",
        "message": "Provider saved",
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "sources": resolved["sources"],
        "provider": sanitize_provider_record(provider or resolved["data"].model_dump()),
    }


async def update_cli_provider(
    *,
    provider_id: str,
    user_id: Optional[str] = None,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    max_model_len: Optional[int] = None,
    supports_multimodal: Optional[bool] = None,
    supports_structured_output: Optional[bool] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    data = _build_provider_update_data(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        max_model_len=max_model_len,
        supports_multimodal=supports_multimodal,
        supports_structured_output=supports_structured_output,
        is_default=is_default,
    )
    provider = await llm_provider_service.update_provider(
        provider_id,
        data,
        user_id=resolved_user_id,
        allow_system_default_update=False,
    )
    return {
        "status": "ok",
        "message": "Provider updated",
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "provider": sanitize_provider_record(provider.to_dict()),
    }


async def delete_cli_provider(*, provider_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    from common.services import llm_provider_service

    resolved_user_id = user_id or get_default_cli_user_id()
    await llm_provider_service.delete_provider(provider_id, user_id=resolved_user_id)
    return {
        "status": "ok",
        "message": "Provider deleted",
        "user_id": resolved_user_id,
        "provider_id": provider_id,
        "deleted": True,
    }

