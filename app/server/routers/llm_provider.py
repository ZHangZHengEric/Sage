from fastapi import APIRouter, Request
from common.core.request_identity import get_request_user_id
from common.core.render import Response
from common.schemas.base import LLMProviderCreate, LLMProviderUpdate
from common.services import llm_provider_service

router = APIRouter(prefix="/api/llm-provider", tags=["LLM Provider"])

@router.post("/verify")
async def verify_provider(data: LLMProviderCreate):
    """
    验证模型提供商配置是否有效
    """
    try:
        await llm_provider_service.verify_provider(data)
        return await Response.succ(message="验证成功")
    except Exception as e:
        return await Response.error(message=f"验证失败: {str(e)}")


@router.post("/verify-capabilities")
async def verify_capabilities(data: LLMProviderCreate):
    """
    验证模型连接并探测关键能力，包括多模态与结构化输出。
    """
    try:
        result = await llm_provider_service.verify_capabilities(data)
        return await Response.succ(message="能力验证成功", data=result)
    except Exception as e:
        return await Response.error(message=f"验证失败: {str(e)}")


@router.post("/verify-multimodal")
async def verify_multimodal(data: LLMProviderCreate):
    """
    验证模型提供商是否支持多模态（图像输入）
    通过发送一张红色图片，验证模型能否正确识别颜色
    """
    try:
        result = await llm_provider_service.verify_multimodal(data)
        return await Response.succ(
            message="多模态验证成功，模型正确识别了图片内容" if result["recognized"] else "模型支持多模态但未能正确识别图片内容",
            data=result,
        )
    except Exception as e:
        return await Response.succ(message="该模型不支持多模态", data={"supports_multimodal": False, "error": str(e)})

@router.get("/list")
async def list_providers(request: Request):
    user_id = get_request_user_id(request)
    return await Response.succ(data=await llm_provider_service.list_providers(user_id))

@router.post("/create")
async def create_provider(data: LLMProviderCreate, request: Request):
    user_id = get_request_user_id(request)
    provider_id = await llm_provider_service.create_provider(data, user_id=user_id)
    return await Response.succ(data={"provider_id": provider_id})

@router.put("/update/{provider_id}")
async def update_provider(provider_id: str, data: LLMProviderUpdate, request: Request):
    user_id = get_request_user_id(request)
    try:
        await llm_provider_service.update_provider(
            provider_id,
            data,
            user_id=user_id,
            allow_system_default_update=False,
        )
        return await Response.succ()
    except PermissionError as e:
        return await Response.error(message=str(e))
    except ValueError as e:
        return await Response.error(message=str(e))

@router.delete("/delete/{provider_id}")
async def delete_provider(provider_id: str, request: Request):
    user_id = get_request_user_id(request)
    try:
        await llm_provider_service.delete_provider(provider_id, user_id=user_id)
        return await Response.succ()
    except PermissionError as e:
        return await Response.error(message=str(e))
    except ValueError as e:
        return await Response.error(message=str(e))
