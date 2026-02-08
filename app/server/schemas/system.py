from typing import Optional
from pydantic import BaseModel

class SystemSettingsRequest(BaseModel):
    allow_registration: bool

class SystemSettingsResponse(BaseModel):
    allow_registration: bool
