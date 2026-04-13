"""LLMProvider ORM + DAO (shared by server and desktop)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Boolean, Integer, Float, func, select
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base, BaseDao, get_local_now


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_keys: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=True)
    top_p: Mapped[float] = mapped_column(Float, nullable=True)
    presence_penalty: Mapped[float] = mapped_column(Float, nullable=True)
    max_model_len: Mapped[int] = mapped_column(Integer, nullable=True)
    supports_multimodal: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_structured_output: Mapped[bool] = mapped_column(Boolean, default=False)
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
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
        top_p: float = 0.95,
        presence_penalty: float = 0.0,
        max_model_len: int = 96000,
        supports_multimodal: bool = False,
        supports_structured_output: bool = False,
        is_default: bool = False,
        user_id: str = "",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.base_url = base_url
        self.api_keys = self.normalize_api_keys(api_keys)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.max_model_len = max_model_len
        self.supports_multimodal = supports_multimodal
        self.supports_structured_output = supports_structured_output
        self.is_default = is_default
        self.user_id = user_id
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()

    @staticmethod
    def normalize_api_keys(api_keys: Optional[List[str]]) -> List[str]:
        if not api_keys:
            raise ValueError("Exactly one API key is required")

        normalized_keys = [str(key).strip() for key in api_keys if str(key).strip()]
        if len(normalized_keys) != 1:
            raise ValueError("Exactly one API key is required")

        api_key = normalized_keys[0]
        if "\n" in api_key or "\r" in api_key:
            raise ValueError("API key must be a single line")

        return [api_key]

    @property
    def api_key(self) -> Optional[str]:
        return self.api_keys[0] if self.api_keys else None

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
            "supports_multimodal": self.supports_multimodal,
            "supports_structured_output": self.supports_structured_output,
            "is_default": self.is_default,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class LLMProviderDao(BaseDao):
    """LLM Provider 数据访问对象（共享 DAO）。"""

    async def save(self, provider: "LLMProvider") -> bool:
        provider.api_keys = LLMProvider.normalize_api_keys(provider.api_keys)
        provider.updated_at = get_local_now()
        return await BaseDao.save(self, provider)

    async def get_by_id(self, provider_id: str) -> Optional["LLMProvider"]:
        return await BaseDao.get_by_id(self, LLMProvider, provider_id)

    async def get_by_config(
        self,
        *,
        base_url: str,
        model: str,
        user_id: Optional[str] = None,
    ) -> List["LLMProvider"]:
        where = [
            LLMProvider.base_url == base_url,
            LLMProvider.model == model,
        ]
        if user_id is not None:
            where.append(LLMProvider.user_id == user_id)
        return await BaseDao.get_list(
            self,
            LLMProvider,
            where=where,
            order_by=LLMProvider.created_at.desc(),
            limit=100,
        )

    async def get_list(self, user_id: Optional[str] = None) -> List["LLMProvider"]:
        where = []
        if user_id is not None:
            where.append(LLMProvider.user_id == user_id)
        limit = 100
        return await BaseDao.get_list(
            self,
            LLMProvider,
            where=where or None,
            order_by=LLMProvider.created_at.desc(),
            limit=limit,
        )

    async def delete_by_id(self, provider_id: str) -> bool:
        return await BaseDao.delete_by_id(self, LLMProvider, provider_id)

    async def get_default(self, user_id: Optional[str] = None) -> Optional["LLMProvider"]:
        where = [LLMProvider.is_default == True]  # noqa: E712
        if user_id is not None:
            where.append(LLMProvider.user_id == user_id)
        return await BaseDao.get_first(self, LLMProvider, where=where)
