from __future__ import annotations

from fastapi.responses import JSONResponse
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error

from app.server_v2.core.observability.context import get_request_id

REASON_STATUS = {
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "validation": 422,
    "unavailable": 503,
    "rate_limited": 429,
    "internal": 500,
}


class ServerV2Error(Exception):
    def __init__(self, reason: str, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.detail = detail

    @property
    def status_code(self) -> int:
        return REASON_STATUS.get(self.reason, 400)


def current_request_id() -> str:
    return get_request_id()


def success(data: object = None) -> dict[str, object]:
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "request_id": current_request_id(),
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
        "request_id": current_request_id(),
    }


def error_response(
    *,
    status_code: int,
    message: str,
    detail: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(
            status_code=status_code, message=message, detail=detail
        ),
    )


def map_sage_error(exc: SageV2Error) -> ServerV2Error:
    return map_error_info(exc.info)


def map_error_info(info) -> ServerV2Error:
    """Classify one runtime error, however it reached us.

    Commands report failure as a ``CommandReceipt`` carrying a
    ``RuntimeErrorInfo`` rather than by raising, so the same classification has
    to be reachable without an exception to unwrap. Keeping one implementation
    means a rejected command and a raised error of the same category cannot be
    reported to a client as two different things.
    """

    if info.code.endswith("not_found"):
        reason = "not_found"
    elif info.category == ErrorCategory.RATE_LIMITED:
        reason = "rate_limited"
    elif info.category == ErrorCategory.CONFLICT:
        reason = "conflict"
    elif info.category == ErrorCategory.AUTHENTICATION:
        reason = "unauthenticated"
    elif info.category == ErrorCategory.AUTHORIZATION:
        reason = "forbidden"
    else:
        reason = "validation"
    return ServerV2Error(reason, info.message, detail=info.code)
