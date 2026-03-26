from typing import List, Optional
from pydantic import BaseModel, field_validator
from datetime import datetime


def _validate_single_api_key(api_keys: List[str]) -> List[str]:
    normalized_keys = [key.strip() for key in api_keys if key and key.strip()]
    if len(normalized_keys) != 1:
        raise ValueError("Exactly one API key is required")
    if any("\n" in key or "\r" in key for key in normalized_keys):
        raise ValueError("API key must be a single line")
    return normalized_keys

class LLMProviderBase(BaseModel):
    name: str
    base_url: str
    api_keys: List[str]
    model: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    max_model_len: Optional[int] = None
    supports_multimodal: bool = False
    is_default: bool = False

    @field_validator("api_keys")
    @classmethod
    def validate_api_keys(cls, value: List[str]) -> List[str]:
        return _validate_single_api_key(value)

class LLMProviderCreate(LLMProviderBase):
    pass

class LLMProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_keys: Optional[List[str]] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    max_model_len: Optional[int] = None
    supports_multimodal: Optional[bool] = None
    is_default: Optional[bool] = None

    @field_validator("api_keys")
    @classmethod
    def validate_api_keys(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value
        return _validate_single_api_key(value)

class LLMProviderDTO(LLMProviderBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
