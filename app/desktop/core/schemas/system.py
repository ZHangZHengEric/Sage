from typing import Optional, Dict
from pydantic import BaseModel

class SystemSettingsRequest(BaseModel):
    allow_registration: bool

class SystemInfoResponse(BaseModel):
    allow_registration: bool
    has_model_provider: bool
    has_agent: bool

class TauriPlatform(BaseModel):
    signature: str
    url: str

class TauriUpdateResponse(BaseModel):
    version: str
    notes: str
    pub_date: str
    platforms: Dict[str, TauriPlatform]
