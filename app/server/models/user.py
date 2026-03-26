from datetime import datetime
from typing import Optional

from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, Dict, Any

from .base import Base, BaseDao, get_local_now


class UserConfig(Base):
    __tablename__ = "user_configs"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default={})
    updated_at: Mapped[datetime] = mapped_column(default=get_local_now, onupdate=get_local_now)

    def __init__(self, user_id: str, config: Dict[str, Any] = None):
        self.user_id = user_id
        self.config = config or {}
        self.updated_at = get_local_now()


class UserConfigDao(BaseDao):
    async def get_config(self, user_id: str) -> Dict[str, Any]:
        obj = await BaseDao.get_by_id(self, UserConfig, user_id)
        return obj.config if obj else {}

    async def update_config(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        obj = await BaseDao.get_by_id(self, UserConfig, user_id)
        if not obj:
            obj = UserConfig(user_id=user_id, config=updates)
            await BaseDao.insert(self, obj)
        else:
            # Deep merge or shallow merge? Shallow for now.
            new_config = obj.config.copy()
            new_config.update(updates)
            obj.config = new_config
            await BaseDao.save(self, obj)
        return obj.config


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    nickname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phonenum: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="user")
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        nickname: Optional[str] = None,
        email: Optional[str] = None,
        phonenum: Optional[str] = None,
        role: str = "user",
        avatar_url: Optional[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.username = username
        self.nickname = nickname
        self.password_hash = password_hash
        self.email = email
        self.phonenum = phonenum
        self.role = role
        self.avatar_url = avatar_url
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class UserExternalIdentity(Base):
    __tablename__ = "user_external_identities"

    identity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default={})
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        identity_id: str,
        user_id: str,
        provider_id: str,
        provider_subject: str,
        provider_username: Optional[str] = None,
        provider_email: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.identity_id = identity_id
        self.user_id = user_id
        self.provider_id = provider_id
        self.provider_subject = provider_subject
        self.provider_username = provider_username
        self.provider_email = provider_email
        self.profile = profile or {}
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class UserDao(BaseDao):
    """用户数据访问层"""

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """根据用户ID查询用户"""
        return await BaseDao.get_by_id(self, User, user_id)

    async def get_by_username(self, username: str) -> Optional[User]:
        """根据用户名查询用户"""
        return await BaseDao.get_first(self, User, where=[User.username == username])

    async def get_by_email(self, email: str) -> Optional[User]:
        """根据邮箱查询用户"""
        return await BaseDao.get_first(self, User, where=[User.email == email])

    async def save(self, user: User) -> bool:
        """保存用户"""
        user.updated_at = get_local_now()
        return await BaseDao.save(self, user)
    
    async def get_list(self, limit: int = 100) -> list[User]:
        """查询所有用户"""
        return await BaseDao.get_list(self, User, limit=limit)


class UserExternalIdentityDao(BaseDao):
    async def get_by_provider_subject(self, provider_id: str, provider_subject: str) -> Optional[UserExternalIdentity]:
        return await BaseDao.get_first(
            self,
            UserExternalIdentity,
            where=[
                UserExternalIdentity.provider_id == provider_id,
                UserExternalIdentity.provider_subject == provider_subject,
            ],
        )

    async def get_by_user_provider(self, user_id: str, provider_id: str) -> Optional[UserExternalIdentity]:
        return await BaseDao.get_first(
            self,
            UserExternalIdentity,
            where=[
                UserExternalIdentity.user_id == user_id,
                UserExternalIdentity.provider_id == provider_id,
            ],
        )

    async def save(self, identity: UserExternalIdentity) -> bool:
        identity.updated_at = get_local_now()
        return await BaseDao.save(self, identity)
