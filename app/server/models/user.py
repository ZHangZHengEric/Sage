from datetime import datetime
from typing import Optional

from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, Dict, Any

from .base import Base, BaseDao


class UserConfig(Base):
    __tablename__ = "user_configs"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default={})
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)

    def __init__(self, user_id: str, config: Dict[str, Any] = None):
        self.user_id = user_id
        self.config = config or {}
        self.updated_at = datetime.now()


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
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phonenum: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="user")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        email: Optional[str] = None,
        phonenum: Optional[str] = None,
        role: str = "user",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self.phonenum = phonenum
        self.role = role
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()


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
        user.updated_at = datetime.now()
        return await BaseDao.save(self, user)
    
    async def get_list(self, limit: int = 100) -> list[User]:
        """查询所有用户"""
        return await BaseDao.get_list(self, User, limit=limit)
