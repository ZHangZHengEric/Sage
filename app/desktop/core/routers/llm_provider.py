from typing import List
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException
from common.core.render import Response
from common.models.llm_provider import LLMProvider, LLMProviderDao
from common.schemas.base import LLMProviderCreate, LLMProviderUpdate
from common.core.client.chat import init_chat_client
from loguru import logger
from openai import AsyncOpenAI

router = APIRouter(prefix="/api/llm-provider", tags=["LLM Provider"])

@router.post("/verify")
async def verify_provider(data: LLMProviderCreate):
    """
    验证模型提供商配置是否有效
    """
    try:
        api_key = data.api_keys[0] if data.api_keys else None
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
        logger.error(f"模型提供商验证失败: {e}")
        return await Response.error(message=f"验证失败: {str(e)}")


@router.post("/verify-multimodal")
async def verify_multimodal(data: LLMProviderCreate):
    """
    验证模型提供商是否支持多模态（图像输入）
    通过发送一张红色图片，验证模型能否正确识别颜色
    """
    try:
        api_key = data.api_keys[0] if data.api_keys else None
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
        logger.error(f"多模态验证失败: {e}")
        return await Response.succ(message="该模型不支持多模态", data={"supports_multimodal": False, "error": str(e)})

@router.get("/list")
async def list_providers(request: Request):
    dao = LLMProviderDao()
    providers = await dao.get_list()
    resp_dict = [provider.to_dict() for provider in providers]
    return await Response.succ(data=resp_dict)

@router.post("/create")
async def create_provider(data: LLMProviderCreate, request: Request):
    dao = LLMProviderDao()

    # Normalize base_url: remove trailing slash for consistent comparison
    normalized_base_url = data.base_url.rstrip('/') if data.base_url else data.base_url

    # Check if provider already exists (match by base_url, model, and api_keys)
    existing_providers = await dao.get_by_config(base_url=normalized_base_url, model=data.model)
    logger.info(f"[LLMProvider] Checking existing providers for base_url={normalized_base_url}, model={data.model}, found {len(existing_providers)} candidates")
    logger.info(f"[LLMProvider] Request api_keys: {data.api_keys}")
    
    for provider in existing_providers:
        logger.info(f"[LLMProvider] Comparing with provider {provider.id}: api_keys={provider.api_keys}")
        # Compare api_keys - handle both single and multiple keys
        # Sort both lists to ensure consistent comparison
        if sorted(provider.api_keys) == sorted(data.api_keys):
            logger.info(f"[LLMProvider] Found matching provider: {provider.id}")
            return await Response.succ(data={"provider_id": provider.id})
    
    logger.info("[LLMProvider] No matching provider found, creating new one")

    # Auto-generate name if not provided
    provider_name = data.name
    if not provider_name:
        # Generate name from model and base_url (use normalized base_url)
        provider_name = f"{data.model}@{normalized_base_url.replace('https://', '').replace('http://', '').split('/')[0]}"

    provider_id = str(uuid.uuid4())
    provider = LLMProvider(
        id=provider_id,
        name=provider_name,
        base_url=normalized_base_url,  # Use normalized base_url
        api_keys=data.api_keys,
        model=data.model,
        max_tokens=data.max_tokens,
        temperature=data.temperature,
        top_p=data.top_p,
        presence_penalty=data.presence_penalty,
        max_model_len=data.max_model_len,
        supports_multimodal=data.supports_multimodal,
        is_default=data.is_default,
    )
    if data.is_default:
        api_key = provider.api_keys[0] if provider.api_keys else None
        base_url = provider.base_url
        model_name = provider.model
        chat_client = await init_chat_client(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
        )
        if chat_client is not None:
            logger.info("LLM Chat 客户端已初始化")
    await dao.save(provider)
    return await Response.succ(data={"provider_id": provider_id})

@router.put("/update/{provider_id}")
async def update_provider(provider_id: str, data: LLMProviderUpdate, request: Request):
    dao = LLMProviderDao()
    provider = await dao.get_by_id(provider_id)
    if not provider:
        return await Response.error(message="Provider not found")
    
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
    dao = LLMProviderDao()
    provider = await dao.get_by_id(provider_id)
    if not provider:
        return await Response.error(message="Provider not found")

    if provider.is_default:
        return await Response.error(message="Cannot delete default provider")
    
    await dao.delete_by_id(provider_id)
    return await Response.succ()
