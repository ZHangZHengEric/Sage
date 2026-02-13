from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class LLMProviderBase(BaseModel):
    name: str
    base_url: str
    api_keys: List[str]
    model: str
    is_default: bool = False

class LLMProviderCreate(LLMProviderBase):
    pass

class LLMProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_keys: Optional[List[str]] = None
    model: Optional[str] = None
    is_default: Optional[bool] = None

class LLMProviderDTO(LLMProviderBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
