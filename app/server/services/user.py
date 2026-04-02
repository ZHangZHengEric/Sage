import time
from typing import Optional, Tuple, List, Dict

import jwt
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from loguru import logger

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.system import SystemInfoDao
from common.models.user import User, UserDao
from common.services.oauth.helpers import (
    build_user_claims as shared_build_user_claims,
    hash_password as shared_hash_password,
)
from .auth.email_verification import (
    normalize_email,
    send_register_email_code,
    verify_register_email_code,
)
from common.utils.id import gen_id

ph = PasswordHasher()


def _hash_password(password: str) -> str:
    return shared_hash_password(password)


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        ph.verify(password_hash, password)
        return True
    except (argon2_exceptions.VerifyMismatchError, argon2_exceptions.VerificationError):
        return False
    except Exception:
        return False


def _gen_tokens(user: User) -> Tuple[str, str, int]:
    cfg = config.get_startup_config()
    exp_seconds = int(cfg.jwt_expire_hours) * 60 * 60
    now = int(time.time())
    access_claims = build_user_claims(user)
    access_claims["exp"] = now + exp_seconds
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


def hash_password(password: str) -> str:
    return shared_hash_password(password)


def create_login_tokens(user: User) -> Tuple[str, str, int]:
    return _gen_tokens(user)


def build_user_claims(user: User) -> Dict[str, str]:
    return shared_build_user_claims(user)


async def register_user(
    username: str,
    password: str,
    email: Optional[str] = None,
    phonenum: Optional[str] = None,
    verification_code: Optional[str] = None,
) -> str:
    # Check if registration is allowed
    sys_dao = SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    if allow_reg == "false":
        raise SageHTTPException(
            status_code=500, detail="系统不允许自注册", error_detail="registration disabled"
        )

    email = normalize_email(email)
    if not email:
        raise SageHTTPException(
            status_code=400, detail="注册必须填写邮箱", error_detail="email is required"
        )

    dao = UserDao()
    existing = await dao.get_by_username(username)
    if existing:
        raise SageHTTPException(
            status_code=500, detail="用户名已存在", error_detail=username
        )
    if email:
        existing_email = await dao.get_by_email(email)
        if existing_email:
            raise SageHTTPException(
                status_code=500, detail="邮箱已存在", error_detail=email
            )

    await verify_register_email_code(email, verification_code or "")

    user_id = gen_id()
    password_hash = _hash_password(password)
    user = User(
        user_id=user_id,
        username=username,
        password_hash=password_hash,
        email=email,
        phonenum=phonenum,
    )
    await dao.save(user)
    logger.info(f"用户注册成功: {username}")
    return user_id


async def send_register_verification_code(email: str) -> tuple[int, int]:
    sys_dao = SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    if allow_reg == "false":
        raise SageHTTPException(
            status_code=500, detail="系统不允许自注册", error_detail="registration disabled"
        )

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise SageHTTPException(
            status_code=400, detail="请输入邮箱地址", error_detail="email is required"
        )

    dao = UserDao()
    existing_email = await dao.get_by_email(normalized_email)
    if existing_email:
        raise SageHTTPException(
            status_code=500, detail="邮箱已存在", error_detail=normalized_email
        )

    return await send_register_email_code(normalized_email)


async def login_user(username_or_email: str, password: str) -> Tuple[str, str, int]:
    user = await authenticate_user(username_or_email, password)
    return create_login_tokens(user)


async def authenticate_user(username_or_email: str, password: str) -> User:
    dao = UserDao()
    user = await dao.get_by_username(username_or_email)
    if not user and "@" in username_or_email:
        user = await dao.get_by_email(username_or_email)

    if not user or not _verify_password(password, user.password_hash):
        raise SageHTTPException(detail="用户名或密码错误", error_detail="invalid credentials")
    return user


async def change_password(user_id: str, old_password: str, new_password: str) -> None:
    dao = UserDao()
    user = await dao.get_by_id(user_id)
    if not user:
        # Check if it's admin (admin user in config cannot change password via this API)
        if user_id == "admin":
            raise SageHTTPException(detail="管理员账户请通过配置文件修改密码", error_detail="admin password immutable via api")
        raise SageHTTPException(detail="用户不存在", error_detail="user not found")

    if not _verify_password(old_password, user.password_hash):
        raise SageHTTPException(detail="旧密码错误", error_detail="invalid old password")

    user.password_hash = _hash_password(new_password)
    await dao.save(user)
    logger.info(f"用户修改密码成功: {user.username}")


async def get_user_list(page: int = 1, page_size: int = 20) -> Tuple[List[User], int]:
    dao = UserDao()
    return await dao.paginate_list(User, order_by=User.created_at.desc(), page=page, page_size=page_size)


async def delete_user(user_id: str) -> bool:
    dao = UserDao()
    user = await dao.get_by_id(user_id)
    if not user:
        raise SageHTTPException(detail="用户不存在", error_detail="user not found")
    if user.role == "admin":
        raise SageHTTPException(detail="无法删除管理员用户", error_detail="cannot delete admin")
    await dao.delete_by_id(User, user_id)
    return True


async def add_user(
    username: str,
    password: str,
    role: str = "user",
    email: Optional[str] = None,
    phonenum: Optional[str] = None,
) -> str:
    email = normalize_email(email) or None
    dao = UserDao()
    existing = await dao.get_by_username(username)
    if existing:
        raise SageHTTPException(
            status_code=500, detail="用户名已存在", error_detail=username
        )
    if email:
        existing_email = await dao.get_by_email(email)
        if existing_email:
            raise SageHTTPException(
                status_code=500, detail="邮箱已存在", error_detail=email
            )
    
    user_id = gen_id()
    password_hash = _hash_password(password)
    user = User(
        user_id=user_id,
        username=username,
        password_hash=password_hash,
        email=email,
        phonenum=phonenum,
        role=role
    )
    await dao.save(user)
    logger.info(f"管理员添加用户成功: {username}")
    return user_id


async def get_user_options() -> List[dict]:
    """Get simplified user list for selection options"""
    dao = UserDao()
    # Fetch up to 1000 users for dropdown
    users = await dao.get_list(limit=1000)
    return [{"label": u.username, "value": u.user_id} for u in users]
