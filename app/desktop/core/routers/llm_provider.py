from typing import List
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException
from ..models.llm_provider import LLMProvider, LLMProviderDao
from ..schemas.llm_provider import LLMProviderDTO, LLMProviderCreate, LLMProviderUpdate
from ..core.render import Response
from ..core.client.chat import init_chat_client
from loguru import logger

router = APIRouter(prefix="/api/llm-provider", tags=["LLM Provider"])

@router.get("/list")
async def list_providers(request: Request):
    dao = LLMProviderDao()
    providers = await dao.get_list()
    resp_dict = [provider.to_dict() for provider in providers]
    return await Response.succ(data=resp_dict)

@router.post("/create")
async def create_provider(data: LLMProviderCreate, request: Request):
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
    return await Response.succ()

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
