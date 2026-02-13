from typing import List
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException
from ..models.llm_provider import LLMProvider, LLMProviderDao
from ..schemas.llm_provider import LLMProviderDTO, LLMProviderCreate, LLMProviderUpdate
from ..core.render import Response

router = APIRouter(prefix="/api/llm-provider", tags=["LLM Provider"])

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
        is_default=False,
        user_id=user_id
    )
    await dao.save(provider)
    return await Response.succ()

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
