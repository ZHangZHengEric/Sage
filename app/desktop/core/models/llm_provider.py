"""
LLM Provider 模型（SQLAlchemy ORM）
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Boolean, or_, select, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_keys: Mapped[List[str]] = mapped_column(JSON, nullable=False)  # List of keys
    model: Mapped[str] = mapped_column(String(255), nullable=False)    # Model name
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=True)
    top_p: Mapped[float] = mapped_column(Float, nullable=True)
    presence_penalty: Mapped[float] = mapped_column(Float, nullable=True)
    max_model_len: Mapped[int] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        id: str,
        name: str,
        base_url: str,
        api_keys: List[str],
        model: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        max_model_len: Optional[int] = None,
        is_default: bool = False,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.base_url = base_url
        self.api_keys = api_keys
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.max_model_len = max_model_len
        self.is_default = is_default
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_keys": self.api_keys,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "max_model_len": self.max_model_len,
            "is_default": self.is_default,
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

    async def get_list(self) -> List["LLMProvider"]:
        limit = 100
        return await BaseDao.get_list(self, LLMProvider, order_by=LLMProvider.created_at.desc(), limit=limit)

    async def delete_by_id(self, provider_id: str) -> bool:
        return await BaseDao.delete_by_id(self, LLMProvider, provider_id)

    async def get_default(self) -> Optional["LLMProvider"]:
        where = [LLMProvider.is_default == True]
        return await BaseDao.get_first(self, LLMProvider, where=where)
