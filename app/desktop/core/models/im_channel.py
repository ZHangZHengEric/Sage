"""
IM Channel configuration model (SQLAlchemy ORM)

Multi-tenant support: each user can have their own IM configurations.
"""

from datetime import datetime
from typing import Any, Dict, Optional, List

from sqlalchemy import JSON, String, Boolean, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


# Default Sage user ID for desktop app
DEFAULT_SAGE_USER_ID = "desktop_default_user"


class IMChannelConfig(Base):
    """IM Channel configuration model - one row per user per provider."""
    __tablename__ = "im_user_configs"

    # Composite primary key: sage_user_id + provider
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sage_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_SAGE_USER_ID)
    provider: Mapped[str] = mapped_column(String(36), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint('id'),
    )

    def __init__(
        self,
        sage_user_id: str = DEFAULT_SAGE_USER_ID,
        provider: str = "",
        config: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.sage_user_id = sage_user_id
        self.provider = provider
        self.config = config or {}
        self.enabled = enabled
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()


class IMChannelConfigDao(BaseDao):
    """
    IM Channel configuration DAO - multi-tenant support
    """

    async def get_config(
        self,
        provider: str,
        sage_user_id: str = DEFAULT_SAGE_USER_ID
    ) -> Optional["IMChannelConfig"]:
        """Get IM config by provider and user."""
        db = await self._get_db()
        async with db.get_session(autocommit=False) as session:
            from sqlalchemy import select, and_
            result = await session.execute(
                select(IMChannelConfig).where(
                    and_(
                        IMChannelConfig.sage_user_id == sage_user_id,
                        IMChannelConfig.provider == provider
                    )
                )
            )
            return result.scalar_one_or_none()

    async def get_all_configs(
        self,
        sage_user_id: str = DEFAULT_SAGE_USER_ID
    ) -> Dict[str, Dict[str, Any]]:
        """Get all IM configs for a user."""
        db = await self._get_db()
        async with db.get_session(autocommit=False) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(IMChannelConfig).where(
                    IMChannelConfig.sage_user_id == sage_user_id
                )
            )
            configs = result.scalars().all()
            result_dict = {}
            for config in configs:
                # Merge config JSON with database fields
                # Database 'enabled' field takes precedence over config['enabled']
                merged_config = {
                    **config.config,
                    "enabled": config.enabled  # Use database field, not config JSON
                }
                result_dict[config.provider] = merged_config
            return result_dict

    async def save_config(
        self,
        provider: str,
        config: Dict[str, Any],
        sage_user_id: str = DEFAULT_SAGE_USER_ID
    ) -> IMChannelConfig:
        """Save or update IM config for provider and user.

        Note: 'enabled' is stored in the database table field, not in config JSON.
        """
        db = await self._get_db()
        async with db.get_session() as session:
            from sqlalchemy import select, and_

            # Check if exists
            result = await session.execute(
                select(IMChannelConfig).where(
                    and_(
                        IMChannelConfig.sage_user_id == sage_user_id,
                        IMChannelConfig.provider == provider
                    )
                )
            )
            existing = result.scalar_one_or_none()

            now = datetime.now()
            # Get enabled from config JSON, default to False
            enabled = config.get('enabled', False)

            # Remove 'enabled' from config JSON to avoid duplication
            # 'enabled' is stored in the database table field only
            config_copy = {k: v for k, v in config.items() if k != 'enabled'}

            if existing:
                existing.config = config_copy
                existing.enabled = enabled
                existing.updated_at = now
                await session.merge(existing)
                return existing
            else:
                obj = IMChannelConfig(
                    sage_user_id=sage_user_id,
                    provider=provider,
                    config=config_copy,
                    enabled=enabled,
                    created_at=now,
                    updated_at=now
                )
                session.add(obj)
                return obj

    async def delete_config(
        self,
        provider: str,
        sage_user_id: str = DEFAULT_SAGE_USER_ID
    ) -> bool:
        """Delete IM config for provider and user."""
        db = await self._get_db()
        async with db.get_session() as session:
            from sqlalchemy import and_, delete

            result = await session.execute(
                delete(IMChannelConfig).where(
                    and_(
                        IMChannelConfig.sage_user_id == sage_user_id,
                        IMChannelConfig.provider == provider
                    )
                )
            )
            return result.rowcount > 0

    async def list_user_configs(
        self,
        sage_user_id: str = DEFAULT_SAGE_USER_ID
    ) -> List[IMChannelConfig]:
        """List all IM configs for a user."""
        db = await self._get_db()
        async with db.get_session(autocommit=False) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(IMChannelConfig).where(
                    IMChannelConfig.sage_user_id == sage_user_id
                )
            )
            return list(result.scalars().all())

    async def get_all_configs_all_users(
        self
    ) -> List[IMChannelConfig]:
        """List all IM configs for all users (debug use)."""
        db = await self._get_db()
        async with db.get_session(autocommit=False) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(IMChannelConfig)
            )
            return list(result.scalars().all())
