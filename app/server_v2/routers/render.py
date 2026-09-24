from __future__ import annotations

from fastapi.responses import JSONResponse
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

from app.server_v2.observability.context import get_request_id

_CATEGORY_STATUS = {
    ErrorCategory.AUTHENTICATION: 401,
    ErrorCategory.AUTHORIZATION: 403,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.RATE_LIMITED: 429,
}


def status_for_error(info: RuntimeErrorInfo) -> int:
    if info.code.endswith("not_found"):
        return 404
    return _CATEGORY_STATUS.get(info.category, 422)


def detail_for_error(info: RuntimeErrorInfo) -> str:
    detail = info.metadata.get("detail")
    if isinstance(detail, str):
        return detail
    return "" if info.code.startswith("server.") else info.code


def success(data: object = None) -> dict[str, object]:
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "request_id": get_request_id(),
    }


def error_payload(
    *,
    status_code: int,
    message: str,
    detail: str = "",
) -> dict[str, object]:
    return {
        "code": status_code,
        "message": message,
        "data": None,
        "error_detail": detail,
        "request_id": get_request_id(),
    }


def error_response(
    *,
    status_code: int,
    message: str,
    detail: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(status_code=status_code, message=message, detail=detail),
    )
