"""
IM Channel configuration model (SQLAlchemy ORM)
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class IMChannelConfig(Base):
    """IM Channel configuration model - one row per provider."""
    __tablename__ = "im_channels"

    # Provider type: feishu, dingtalk, imessage
    provider_type: Mapped[str] = mapped_column(String(36), primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        provider_type: str,
        config: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.provider_type = provider_type
        self.config = config or {}
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()


class IMChannelConfigDao(BaseDao):
    """
    IM Channel configuration DAO - one row per provider
    """

    async def get_config(self, provider_type: str) -> Optional["IMChannelConfig"]:
        """Get IM config by provider type."""
        return await self.get_by_id(IMChannelConfig, provider_type)

    async def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """Get all IM configs."""
        db = await self._get_db()
        async with db.get_session(autocommit=False) as session:
            from sqlalchemy import select
            result = await session.execute(select(IMChannelConfig))
            configs = result.scalars().all()
            return {
                config.provider_type: config.config
                for config in configs
            }

    async def save_config(self, provider_type: str, config: Dict[str, Any]) -> IMChannelConfig:
        """Save or update IM config for provider."""
        db = await self._get_db()
        async with db.get_session() as session:
            existing = await session.get(IMChannelConfig, provider_type)
            now = datetime.now()
            if existing:
                existing.config = config
                existing.updated_at = now
                await session.merge(existing)
                return existing
            else:
                obj = IMChannelConfig(provider_type=provider_type, config=config, created_at=now, updated_at=now)
                session.add(obj)
                return obj
