from fastapi import APIRouter, Request
from common.core.render import Response
from common.schemas.base import LLMProviderCreate, LLMProviderUpdate
from common.core.client.chat import init_chat_client
from common.services import llm_provider_service
from ..user_context import get_desktop_user_id

router = APIRouter(prefix="/api/llm-provider", tags=["LLM Provider"])


@router.post("/verify")
async def verify_provider(data: LLMProviderCreate):
    """
    验证模型提供商配置是否有效
    """
    try:
        await llm_provider_service.verify_provider(data)
        return await Response.succ(message="llm_provider.verify_success")
    except Exception as e:
        return await Response.error(
            message="llm_provider.verify_failed",
            message_params={"message": str(e)},
        )


@router.post("/verify-capabilities")
async def verify_capabilities(data: LLMProviderCreate):
    """
    验证模型连接并探测关键能力，包括多模态与结构化输出。
    """
    try:
        result = await llm_provider_service.verify_capabilities(data)
        return await Response.succ(
            message="llm_provider.capabilities_success", data=result
        )
    except Exception as e:
        return await Response.error(
            message="llm_provider.verify_failed",
            message_params={"message": str(e)},
        )


@router.post("/verify-multimodal")
async def verify_multimodal(data: LLMProviderCreate):
    """
    验证模型提供商是否支持多模态（图像输入）
    通过发送一张红色图片，验证模型能否正确识别颜色
    """
    try:
        result = await llm_provider_service.verify_multimodal(data)
        if not result["supports_multimodal"]:
            return await Response.succ(
                message="llm_provider.multimodal_not_supported", data=result
            )
        return await Response.succ(
            message="llm_provider.multimodal_recognized"
            if result["recognized"]
            else "llm_provider.multimodal_unrecognized",
            data=result,
        )
    except Exception as e:
        return await Response.succ(
            message="llm_provider.multimodal_not_supported",
            data={"supports_multimodal": False, "error": str(e)},
        )


@router.get("/list")
async def list_providers(request: Request):
    user_id = get_desktop_user_id(request)
    return await Response.succ(data=await llm_provider_service.list_providers(user_id))


@router.post("/create")
async def create_provider(data: LLMProviderCreate, request: Request):
    user_id = get_desktop_user_id(request)
    try:
        provider_id = await llm_provider_service.create_provider(data, user_id=user_id)
        if data.is_default:
            providers = await llm_provider_service.list_providers(user_id)
            provider = next(
                (item for item in providers if item.get("id") == provider_id), None
            )
            if provider:
                chat_client = await init_chat_client(
                    api_key=provider["api_keys"][0]
                    if provider.get("api_keys")
                    else None,
                    base_url=provider.get("base_url"),
                    model_name=provider.get("model"),
                )
                if chat_client is not None:
                    pass
        return await Response.succ(data={"provider_id": provider_id})
    except ValueError as e:
        return await Response.error(message=str(e))


@router.put("/update/{provider_id}")
async def update_provider(provider_id: str, data: LLMProviderUpdate, request: Request):
    user_id = get_desktop_user_id(request)
    try:
        await llm_provider_service.update_provider(
            provider_id,
            data,
            user_id=user_id,
            allow_system_default_update=True,
        )
        return await Response.succ()
    except PermissionError as e:
        return await Response.error(message=str(e))
    except ValueError as e:
        return await Response.error(message=str(e))


@router.delete("/delete/{provider_id}")
async def delete_provider(provider_id: str, request: Request):
    user_id = get_desktop_user_id(request)
    try:
        await llm_provider_service.delete_provider(provider_id, user_id=user_id)
        return await Response.succ()
    except PermissionError as e:
        return await Response.error(message=str(e))
    except ValueError as e:
        return await Response.error(message=str(e))
