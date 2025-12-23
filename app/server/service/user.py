import time
from typing import Optional, Tuple

import config
import jwt
import models
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from common.exceptions import SageHTTPException
from utils.id import gen_id

from sagents.utils.logger import logger

ph = PasswordHasher()


def _hash_password(password: str) -> str:
    return ph.hash(password)


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        ph.verify(password_hash, password)
        return True
    except (argon2_exceptions.VerifyMismatchError, argon2_exceptions.VerificationError):
        return False
    except Exception:
        return False


def _gen_tokens(user: models.User) -> Tuple[str, str, int]:
    cfg = config.get_startup_config()
    exp_seconds = int(cfg.jwt_expire_hours) * 60 * 60
    now = int(time.time())
    access_claims = {
        "userid": user.user_id,
        "username": user.username,
        "phonenum": user.phonenum or "",
        "email": user.email or "",
        "role": user.role,
        "exp": now + exp_seconds,
    }
    refresh_claims = {
        "uid": user.user_id,
        "nonce": gen_id()[:8],
        "iat": now,
    }
    access_token = jwt.encode(access_claims, cfg.jwt_key, algorithm="HS256")
    refresh_token = jwt.encode(
        refresh_claims, cfg.refresh_token_secret, algorithm="HS256"
    )
    return access_token, refresh_token, exp_seconds


def parse_access_token(token: str) -> Optional[dict]:
    cfg = config.get_startup_config()
    try:
        claims = jwt.decode(token, cfg.jwt_key, algorithms=["HS256"])
        return claims
    except jwt.ExpiredSignatureError:
        raise SageHTTPException(
            status_code=401, detail="登录过期", error_detail="token expired"
        )
    except Exception:
        raise SageHTTPException(
            status_code=401, detail="Token非法", error_detail="invalid token"
        )


def parse_refresh_token(token: str) -> Optional[dict]:
    cfg = config.get_startup_config()
    try:
        claims = jwt.decode(token, cfg.refresh_token_secret, algorithms=["HS256"])
        return claims
    except Exception:
        raise SageHTTPException(
            status_code=401, detail="Token非法", error_detail="invalid refresh token"
        )


async def register_user(
    username: str,
    password: str,
    email: Optional[str] = None,
    phonenum: Optional[str] = None,
) -> str:
    dao = models.UserDao()
    existing = await dao.get_by_username(username)
    if existing:
        raise SageHTTPException(
            status_code=400, detail="用户名已存在", error_detail=username
        )
    if email:
        existing_email = await dao.get_by_email(email)
        if existing_email:
            raise SageHTTPException(
                status_code=400, detail="邮箱已存在", error_detail=email
            )
    user_id = gen_id()
    password_hash = _hash_password(password)
    user = models.User(
        user_id=user_id,
        username=username,
        password_hash=password_hash,
        email=email,
        phonenum=phonenum,
    )
    await dao.save(user)
    logger.info(f"用户注册成功: {username}")
    return user_id


async def login_user(username_or_email: str, password: str) -> Tuple[str, str, int]:
    dao = models.UserDao()
    user = await dao.get_by_username(username_or_email)
    if not user and "@" in username_or_email:
        user = await dao.get_by_email(username_or_email)
    if not user:
        raise SageHTTPException(
            status_code=401, detail="用户不存在", error_detail=username_or_email
        )
    if not _verify_password(password, user.password_hash):
        raise SageHTTPException(
            status_code=401, detail="密码错误", error_detail=username_or_email
        )
    return _gen_tokens(user)
