"""
IM Channel configuration model (SQLAlchemy ORM)
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class IMChannelConfig(Base):
    """IM Channel configuration model."""
    __tablename__ = "im_channels"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        user_id: str,
        config: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.config = config or {}
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()


class IMChannelConfigDao(BaseDao):
    """
    IM Channel configuration DAO
    """

    async def get_by_user_id(self, user_id: str) -> Optional["IMChannelConfig"]:
        """Get IM config by user_id."""
        return await self.get_by_id(IMChannelConfig, user_id)

    async def save_config(self, user_id: str, config: Dict[str, Any]) -> IMChannelConfig:
        """Save or update IM config for user."""
        db = await self._get_db()
        async with db.get_session() as session:
            existing = await session.get(IMChannelConfig, user_id)
            now = datetime.now()
            if existing:
                existing.config = config
                existing.updated_at = now
                await session.merge(existing)
                return existing
            else:
                obj = IMChannelConfig(user_id=user_id, config=config, created_at=now, updated_at=now)
                session.add(obj)
                return obj
