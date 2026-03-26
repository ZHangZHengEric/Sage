import uuid

from fastapi import APIRouter, Request, HTTPException
from ..models.llm_provider import LLMProvider, LLMProviderDao
from ..schemas.llm_provider import LLMProviderCreate, LLMProviderUpdate
from ..core.render import Response
from openai import AsyncOpenAI
from loguru import logger

router = APIRouter(prefix="/api/llm-provider", tags=["LLM Provider"])

@router.post("/verify")
async def verify_provider(data: LLMProviderCreate):
    """
    验证模型提供商配置是否有效
    """
    try:
        api_key = data.api_keys[0]
        if not api_key:
             return await Response.error(message="API Key is required")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=data.base_url,
            timeout=10.0
        )

        # 尝试发送一个简单的消息
        await client.chat.completions.create(
            model=data.model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5
        )

        return await Response.succ(message="验证成功")
    except Exception as e:
        logger.error(f"Provider verification failed: {e}")
        return await Response.error(message=f"验证失败: {str(e)}")


@router.post("/verify-multimodal")
async def verify_multimodal(data: LLMProviderCreate):
    """
    验证模型提供商是否支持多模态（图像输入）
    通过发送一张红色图片，验证模型能否正确识别颜色
    """
    try:
        api_key = data.api_keys[0]
        if not api_key:
             return await Response.error(message="API Key is required")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=data.base_url,
            timeout=30.0
        )

        # 使用一张简单的红色图片进行测试（20x20 像素的红色 PNG）
        # 这是一个 base64 编码的红色图片
        test_image_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"

        # 尝试发送一个包含图片的消息，要求模型识别颜色
        response = await client.chat.completions.create(
            model=data.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": test_image_url}},
                        {"type": "text", "text": "What color is this image? Please answer with just the color name."}
                    ]
                }
            ],
            max_tokens=50,
            temperature=0.1  # 低温度以获得更确定的回答
        )

        # 获取模型的回复
        content = response.choices[0].message.content.lower() if response.choices[0].message.content else ""
        logger.info(f"Multimodal verification response: {content}")

        # 检查回复中是否包含颜色相关的关键词
        color_keywords = ['red', '红色', '红', '赤', '绯', '朱', '丹', '绛']
        is_correct = any(keyword in content for keyword in color_keywords)

        if is_correct:
            return await Response.succ(
                message="多模态验证成功，模型正确识别了图片内容",
                data={"supports_multimodal": True, "response": content, "recognized": True}
            )
        else:
            # 模型虽然支持多模态（API 调用成功），但没有正确识别内容
            return await Response.succ(
                message="模型支持多模态但未能正确识别图片内容",
                data={"supports_multimodal": True, "response": content, "recognized": False}
            )

    except Exception as e:
        logger.error(f"Multimodal verification failed: {e}")
        return await Response.succ(message="该模型不支持多模态", data={"supports_multimodal": False, "error": str(e)})

async def get_current_user_id(request: Request) -> str:
    claims = getattr(request.state, "user_claims", None)
    if not claims:
         raise HTTPException(status_code=401, detail="Unauthorized")
    return claims.get("user_id")

@router.get("/list")
async def list_providers(request: Request):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    dao = LLMProviderDao()
    providers = await dao.get_list(user_id=user_id)
    resp_dict = [provider.to_dict() for provider in providers]
    return await Response.succ(data=resp_dict)

@router.post("/create")
async def create_provider(data: LLMProviderCreate, request: Request):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    dao = LLMProviderDao()
    provider_id = str(uuid.uuid4())
    provider = LLMProvider(
        id=provider_id,
        name=data.name,
        base_url=data.base_url,
        api_keys=data.api_keys,
        model=data.model,
        max_tokens=data.max_tokens,
        temperature=data.temperature,
        top_p=data.top_p,
        presence_penalty=data.presence_penalty,
        max_model_len=data.max_model_len,
        supports_multimodal=data.supports_multimodal,
        is_default=False,
        user_id=user_id
    )
    await dao.save(provider)
    return await Response.succ(data=provider.to_dict())

@router.put("/update/{provider_id}")
async def update_provider(provider_id: str, data: LLMProviderUpdate, request: Request):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    dao = LLMProviderDao()
    provider = await dao.get_by_id(provider_id)
    if not provider:
        return await Response.error(message="Provider not found")
    
    # Check ownership
    if provider.user_id and provider.user_id != user_id:
        return await Response.error(message="Permission denied")
    
    # System default check
    if not provider.user_id:
        return await Response.error(message="Cannot modify system default provider")

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

    await dao.save(provider)
    return await Response.succ()

@router.delete("/delete/{provider_id}")
async def delete_provider(provider_id: str, request: Request):
    claims = getattr(request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    dao = LLMProviderDao()
    provider = await dao.get_by_id(provider_id)
    if not provider:
        return await Response.error(message="Provider not found")

    if provider.is_default:
        return await Response.error(message="Cannot delete default provider")
    
    if provider.user_id and provider.user_id != user_id:
        return await Response.error(message="Permission denied")

    await dao.delete_by_id(provider_id)
    return await Response.succ()
