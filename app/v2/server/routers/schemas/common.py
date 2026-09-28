from __future__ import annotations

from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None
    request_id: str = ""

class ErrorBody(BaseModel):
    code: int
    message: str
    data: None = None
    error_detail: str = ""
    request_id: str = ""

class HealthPayload(BaseModel):
    status: str
    protocol: str
    protocol_version: str
    runtime: str
    trace_enabled: bool

AUTH_ERRORS = {
    401: {"model": ErrorBody, "description": "authentication required"},
}

ADMIN_ERRORS = {
    **AUTH_ERRORS,
    403: {"model": ErrorBody, "description": "admin required"},
}

VALIDATION_ERRORS = {
    422: {"model": ErrorBody, "description": "request validation failed"},
}

