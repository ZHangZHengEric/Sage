from datetime import datetime
from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao
from sqlalchemy import select


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

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "phonenum": self.phonenum,
            "role": self.role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class UserDao(BaseDao):
    async def get_by_id(self, user_id: str) -> Optional[User]:
        db = await self._get_db()
        async with db.get_session() as session:
            return await session.get(User, user_id)

    async def get_by_username(self, username: str) -> Optional[User]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(User).where(User.username == username)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def get_by_email(self, email: str) -> Optional[User]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(User).where(User.email == email)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def save(self, user: User) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            user.updated_at = datetime.now()
            await session.merge(user)
            return True
