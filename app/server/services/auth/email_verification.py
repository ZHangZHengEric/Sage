from __future__ import annotations

import asyncio
import re
import secrets
import time
from dataclasses import dataclass

from loguru import logger

from common.core.client.eml import send_register_verification_mail
from common.core.exceptions import SageHTTPException

REGISTER_VERIFICATION_CODE_LENGTH = 6
REGISTER_VERIFICATION_CODE_TTL_SECONDS = 5 * 60
REGISTER_VERIFICATION_RESEND_INTERVAL_SECONDS = 30

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CODE_PATTERN = re.compile(r"^\d{6}$")


@dataclass
class VerificationCodeRecord:
    code: str
    expires_at: float
    resend_available_at: float


_REGISTER_VERIFICATION_CODES: dict[str, VerificationCodeRecord] = {}
_REGISTER_VERIFICATION_CODES_LOCK = asyncio.Lock()


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def validate_register_email(email: str | None) -> str:
    normalized_email = normalize_email(email)
    if not normalized_email:
        raise SageHTTPException(
            status_code=500,
            detail="请输入邮箱地址",
            error_detail="email is required",
        )
    if not _EMAIL_PATTERN.fullmatch(normalized_email):
        raise SageHTTPException(
            status_code=500,
            detail="邮箱格式不正确",
            error_detail="invalid email format",
        )
    return normalized_email


def validate_verification_code(code: str | None) -> str:
    normalized_code = (code or "").strip()
    if not _CODE_PATTERN.fullmatch(normalized_code):
        raise SageHTTPException(
            status_code=500,
            detail="验证码错误",
            error_detail="invalid verification code format",
        )
    return normalized_code


def _purge_expired_codes(now: float) -> None:
    expired_emails = [
        email for email, record in _REGISTER_VERIFICATION_CODES.items()
        if record.expires_at <= now
    ]
    for email in expired_emails:
        _REGISTER_VERIFICATION_CODES.pop(email, None)


def _generate_verification_code() -> str:
    return "".join(
        secrets.choice("0123456789")
        for _ in range(REGISTER_VERIFICATION_CODE_LENGTH)
    )


async def send_register_email_code(email: str) -> tuple[int, int]:
    normalized_email = validate_register_email(email)
    now = time.time()
    code = _generate_verification_code()
    expires_at = now + REGISTER_VERIFICATION_CODE_TTL_SECONDS
    resend_available_at = now + REGISTER_VERIFICATION_RESEND_INTERVAL_SECONDS

    async with _REGISTER_VERIFICATION_CODES_LOCK:
        _purge_expired_codes(now)
        current_record = _REGISTER_VERIFICATION_CODES.get(normalized_email)
        if current_record and current_record.resend_available_at > now:
            remaining_seconds = max(
                1,
                int(current_record.resend_available_at - now + 0.999),
            )
            raise SageHTTPException(
                status_code=500,
                detail=f"验证码发送过于频繁，请 {remaining_seconds} 秒后重试",
                error_detail="verification code send throttled",
            )
        _REGISTER_VERIFICATION_CODES[normalized_email] = VerificationCodeRecord(
            code=code,
            expires_at=expires_at,
            resend_available_at=resend_available_at,
        )

    try:
        await send_register_verification_mail(normalized_email, code)
    except Exception:
        async with _REGISTER_VERIFICATION_CODES_LOCK:
            current_record = _REGISTER_VERIFICATION_CODES.get(normalized_email)
            if current_record and current_record.code == code:
                _REGISTER_VERIFICATION_CODES.pop(normalized_email, None)
        raise

    logger.info(f"注册验证码已生成并发送: {normalized_email}")
    return (
        REGISTER_VERIFICATION_CODE_TTL_SECONDS,
        REGISTER_VERIFICATION_RESEND_INTERVAL_SECONDS,
    )


async def verify_register_email_code(email: str, code: str) -> None:
    normalized_email = validate_register_email(email)
    normalized_code = validate_verification_code(code)
    now = time.time()

    async with _REGISTER_VERIFICATION_CODES_LOCK:
        _purge_expired_codes(now)
        record = _REGISTER_VERIFICATION_CODES.get(normalized_email)
        if not record:
            raise SageHTTPException(
                status_code=500,
                detail="验证码错误",
                error_detail="verification code missing or expired",
            )
        if record.code != normalized_code:
            raise SageHTTPException(
                status_code=500,
                detail="验证码错误",
                error_detail="verification code mismatch",
            )
        _REGISTER_VERIFICATION_CODES.pop(normalized_email, None)

    logger.info(f"注册验证码校验成功: {normalized_email}")
