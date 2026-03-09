from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

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
    is_default: bool = False

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
    is_default: Optional[bool] = None

class LLMProviderDTO(LLMProviderBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
