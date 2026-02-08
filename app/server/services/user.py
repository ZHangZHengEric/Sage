import time
from typing import Optional, Tuple, List

import jwt
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from loguru import logger

from .. import models
from ..core import config
from ..core.exceptions import SageHTTPException
from ..utils.id import gen_id

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


async def register_user(
    username: str,
    password: str,
    email: Optional[str] = None,
    phonenum: Optional[str] = None,
) -> str:
    # Check if registration is allowed
    sys_dao = models.SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    if allow_reg == "false":
        raise SageHTTPException(
            status_code=403, detail="系统不允许自注册", error_detail="registration disabled"
        )

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

    if not user or not _verify_password(password, user.password_hash):
        raise SageHTTPException(status_code=500, detail="用户名或密码错误", error_detail="invalid credentials")
    return _gen_tokens(user)


async def change_password(user_id: str, old_password: str, new_password: str) -> None:
    dao = models.UserDao()
    user = await dao.get_by_id(user_id)
    if not user:
        # Check if it's admin (admin user in config cannot change password via this API)
        if user_id == "admin":
            raise SageHTTPException(status_code=500, detail="管理员账户请通过配置文件修改密码", error_detail="admin password immutable via api")
        raise SageHTTPException(status_code=500, detail="用户不存在", error_detail="user not found")

    if not _verify_password(old_password, user.password_hash):
        raise SageHTTPException(status_code=500, detail="旧密码错误", error_detail="invalid old password")

    user.password_hash = _hash_password(new_password)
    await dao.save(user)
    logger.info(f"用户修改密码成功: {user.username}")


async def get_user_list(page: int = 1, page_size: int = 20) -> Tuple[List[models.User], int]:
    dao = models.UserDao()
    return await dao.paginate_list(models.User, order_by=models.User.created_at.desc(), page=page, page_size=page_size)


async def delete_user(user_id: str) -> bool:
    dao = models.UserDao()
    user = await dao.get_by_id(user_id)
    if not user:
        raise SageHTTPException(status_code=500, detail="用户不存在", error_detail="user not found")
    if user.role == "admin":
        raise SageHTTPException(status_code=500, detail="无法删除管理员用户", error_detail="cannot delete admin")
    await dao.delete_by_id(models.User, user_id)
    return True


async def add_user(
    username: str,
    password: str,
    role: str = "user",
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
        role=role
    )
    await dao.save(user)
    logger.info(f"管理员添加用户成功: {username}")
    return user_id
