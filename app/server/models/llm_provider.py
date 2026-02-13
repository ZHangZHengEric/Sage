"""
LLM Provider 模型（SQLAlchemy ORM）
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Boolean, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_keys: Mapped[List[str]] = mapped_column(JSON, nullable=False)  # List of keys
    model: Mapped[str] = mapped_column(String(255), nullable=False)    # Model name
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        id: str,
        name: str,
        base_url: str,
        api_keys: List[str],
        model: str,
        is_default: bool = False,
        user_id: str = "",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.base_url = base_url
        self.api_keys = api_keys
        self.model = model
        self.is_default = is_default
        self.user_id = user_id
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_keys": self.api_keys,
            "model": self.model,
            "is_default": self.is_default,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

class LLMProviderDao(BaseDao):
    """
    LLM Provider 数据访问对象（DAO）
    """

    async def save(self, provider: "LLMProvider") -> bool:
        provider.updated_at = datetime.now()
        return await BaseDao.save(self, provider)

    async def get_by_id(self, provider_id: str) -> Optional["LLMProvider"]:
        return await BaseDao.get_by_id(self, LLMProvider, provider_id)

    async def get_list(self, user_id: Optional[str] = None) -> List["LLMProvider"]:
        where = [
            LLMProvider.user_id == user_id,
        ]
        limit = 100
        return await BaseDao.get_list(self, LLMProvider, where=where, order_by=LLMProvider.created_at.desc(), limit=limit)

    async def delete_by_id(self, provider_id: str) -> bool:
        return await BaseDao.delete_by_id(self, LLMProvider, provider_id)

    async def get_default(self) -> Optional["LLMProvider"]:
        where = [LLMProvider.is_default == True]
        return await BaseDao.get_first(self, LLMProvider, where=where)
