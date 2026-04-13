from typing import Any, Dict, Generic, List, Optional, TypeVar
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ===== LLM Provider Schemas =====

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
    supports_structured_output: bool = False
    is_default: bool = False

    @field_validator("api_keys")
    @classmethod
    def validate_api_keys(cls, value: List[str]) -> List[str]:
        return _validate_single_api_key(value)


class LLMProviderCreate(LLMProviderBase):
    name: Optional[str] = None


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
    supports_structured_output: Optional[bool] = None
    is_default: Optional[bool] = None

    @field_validator("api_keys")
    @classmethod
    def validate_api_keys(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value
        return _validate_single_api_key(value)


class LLMProviderDTO(LLMProviderBase):
    id: str
    user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===== System Schemas =====


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


class AgentUsageStatsRequest(BaseModel):
    days: int
    agent_id: Optional[str] = None


class AgentUsageStatsResponse(BaseModel):
    usage: Dict[str, int]


# ===== Base Response Schemas =====


TBaseData = TypeVar("TBaseData")


class BaseResponse(BaseModel, Generic[TBaseData]):
    code: int = 200
    message: str = "success"
    data: Optional[TBaseData] = None
    timestamp: float = 0.0

    def __init__(self, **data: Any):  # type: ignore[override]
        import time

        if "timestamp" not in data:
            data["timestamp"] = time.time()
        super().__init__(**data)


# ===== User Schemas =====


class RegisterPayload(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    phonenum: Optional[str] = None


class RegisterRequest(RegisterPayload):
    verification_code: str


class RegisterResponse(BaseModel):
    user_id: str


class RegisterVerificationCodeRequest(BaseModel):
    email: str


class RegisterVerificationCodeResponse(BaseModel):
    expires_in: int
    retry_after: int


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class UserInfoResponse(BaseModel):
    user: Dict[str, Any]
    has_provider: bool = False
    has_agent: bool = False


class UserDTO(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    phonenum: Optional[str] = None
    role: str
    created_at: str


class UserListResponse(BaseModel):
    items: List[UserDTO]
    total: int


class UserAddRequest(RegisterPayload):
    role: Optional[str] = "user"


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserConfigResponse(BaseModel):
    config: Dict[str, Any]


class UserConfigUpdateRequest(BaseModel):
    config: Dict[str, Any]


class UserDeleteRequest(BaseModel):
    user_id: str


# ===== KDB Schemas =====


class SuccessResponse(BaseModel):
    success: bool
    user_id: Optional[str] = None


class KdbAddRequest(BaseModel):
    name: str
    type: str
    intro: Optional[str] = ""
    language: Optional[str] = ""


class KdbAddResponse(BaseModel):
    kdb_id: str
    user_id: str


class KdbUpdateRequest(BaseModel):
    kdb_id: str
    name: Optional[str] = ""
    intro: Optional[str] = ""
    kdb_setting: Optional[Dict[str, Any]] = None


class KdbInfoResponse(BaseModel):
    kdbId: str
    name: str
    intro: str
    type: str
    createdAt: int
    updatedAt: int
    kdbSetting: Optional[Dict[str, Any]] = None
    user_id: str


class KdbRetrieveRequest(BaseModel):
    kdb_id: str
    query: str
    top_k: int = 10


class KdbRetrieveResponse(BaseModel):
    results: List[Dict[str, Any]]
    user_id: str


class KdbListItem(BaseModel):
    id: str
    name: str
    index_name: str
    intro: str
    createTime: str
    dataSource: str
    docNum: int
    cover: str = ""
    defaultColor: bool = True
    user_id: Optional[str] = None
    type: Optional[str] = None


class KdbListResponse(BaseModel):
    list: List[KdbListItem]
    total: int
    user_id: str


class KdbIdRequest(BaseModel):
    kdb_id: str


class KdbDocListItem(BaseModel):
    id: str
    doc_name: str
    status: int
    create_time: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    task_id: str


class KdbDocListResponse(BaseModel):
    list: List[KdbDocListItem]
    total: int
    user_id: str


class KdbDocInfoResponse(BaseModel):
    id: str
    type: str
    dataName: str
    status: int
    createTime: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    taskId: str
    user_id: str


class KdbDocAddByFilesResponse(BaseModel):
    taskId: str
    user_id: str


class KdbDocTaskProcessResponse(BaseModel):
    success: int
    fail: int
    inProgress: int
    waiting: int
    total: int
    taskProcess: float
    user_id: str


class KdbDocTaskRedoRequest(BaseModel):
    kdb_id: str
    task_id: str


# ===== Task (desktop) Schemas =====


class RecurringTaskBase(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: str
    cron_expression: str
    enabled: bool = True


class RecurringTaskCreate(RecurringTaskBase):
    pass


class OneTimeTaskCreate(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: str
    execute_at: datetime


class OneTimeTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    execute_at: Optional[datetime] = None


class RecurringTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    cron_expression: Optional[str] = None
    enabled: Optional[bool] = None


class RecurringTaskResponse(RecurringTaskBase):
    id: int
    user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_executed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    agent_id: str
    session_id: Optional[str] = None
    execute_at: datetime
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    recurring_task_id: Optional[int] = None

    @field_validator("retry_count", "max_retries", mode="before")
    @classmethod
    def normalize_optional_retry_fields(cls, value):
        return 0 if value is None else value

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    items: List[RecurringTaskResponse]
    total: int
    page: int
    page_size: int


class OneTimeTaskListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskHistoryListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int


__all__ = [
    # LLM provider
    "LLMProviderBase",
    "LLMProviderCreate",
    "LLMProviderUpdate",
    "LLMProviderDTO",
    # System
    "SystemSettingsRequest",
    "SystemInfoResponse",
    "TauriPlatform",
    "TauriUpdateResponse",
    "AgentUsageStatsRequest",
    "AgentUsageStatsResponse",
    # BaseResponse
    "BaseResponse",
    # User
    "RegisterPayload",
    "RegisterRequest",
    "RegisterResponse",
    "RegisterVerificationCodeRequest",
    "RegisterVerificationCodeResponse",
    "LoginRequest",
    "LoginResponse",
    "UserInfoResponse",
    "UserDTO",
    "UserListResponse",
    "UserAddRequest",
    "ChangePasswordRequest",
    "UserConfigResponse",
    "UserConfigUpdateRequest",
    "UserDeleteRequest",
    # KDB
    "SuccessResponse",
    "KdbAddRequest",
    "KdbAddResponse",
    "KdbUpdateRequest",
    "KdbInfoResponse",
    "KdbRetrieveRequest",
    "KdbRetrieveResponse",
    "KdbListItem",
    "KdbListResponse",
    "KdbIdRequest",
    "KdbDocListItem",
    "KdbDocListResponse",
    "KdbDocInfoResponse",
    "KdbDocAddByFilesResponse",
    "KdbDocTaskProcessResponse",
    "KdbDocTaskRedoRequest",
    # Task (desktop)
    "RecurringTaskBase",
    "RecurringTaskCreate",
    "OneTimeTaskCreate",
    "OneTimeTaskUpdate",
    "RecurringTaskUpdate",
    "RecurringTaskResponse",
    "TaskResponse",
    "TaskListResponse",
    "OneTimeTaskListResponse",
    "TaskHistoryListResponse",
]
