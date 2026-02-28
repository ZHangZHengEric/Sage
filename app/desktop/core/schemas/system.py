from typing import Optional
from pydantic import BaseModel

class SystemSettingsRequest(BaseModel):
    allow_registration: bool

class SystemInfoResponse(BaseModel):
    allow_registration: bool
    has_model_provider: bool
    has_agent: bool
