"""OAuth2-related ORM + DAO (shared)."""

from datetime import datetime
from typing import Any, Dict, Optional

from authlib.integrations.sqla_oauth2 import (
    OAuth2AuthorizationCodeMixin,
    OAuth2ClientMixin,
    OAuth2TokenMixin,
)
from sqlalchemy import Boolean, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base, BaseDao, get_local_now


class OAuth2Client(Base, OAuth2ClientMixin):
    __tablename__ = "oauth2_clients"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    skip_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extra_config: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default={}
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        enabled: bool = True,
        skip_consent: bool = True,
        extra_config: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.enabled = enabled
        self.skip_consent = skip_consent
        self.extra_config = extra_config or {}
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class OAuth2AuthorizationCode(Base, OAuth2AuthorizationCodeMixin):
    __tablename__ = "oauth2_authorization_codes"

    code_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        code_id: str,
        user_id: str,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.code_id = code_id
        self.user_id = user_id
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class OAuth2Token(Base, OAuth2TokenMixin):
    __tablename__ = "oauth2_tokens"

    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    grant_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="authorization_code"
    )
    token_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default={}
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        token_id: str,
        user_id: str,
        grant_type: str = "authorization_code",
        token_metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.token_id = token_id
        self.user_id = user_id
        self.grant_type = grant_type
        self.token_metadata = token_metadata or {}
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()

    def get_user(self):
        return getattr(self, "_user", None)

    def get_client(self):
        return getattr(self, "_client", None)

    def bind_entities(self, user=None, client=None):
        if user is not None:
            self._user = user
        if client is not None:
            self._client = client
        return self


class OAuth2ClientDao(BaseDao):
    async def get_by_client_id(self, client_id: str) -> Optional[OAuth2Client]:
        return await BaseDao.get_first(
            self,
            OAuth2Client,
            where=[OAuth2Client.client_id == client_id],
        )

    async def get_all_clients(self) -> list[OAuth2Client]:
        return await BaseDao.get_all(
            self, OAuth2Client, order_by=OAuth2Client.client_id.asc()
        )

    async def save(self, client: OAuth2Client) -> bool:
        client.updated_at = get_local_now()
        return await BaseDao.save(self, client)


class OAuth2AuthorizationCodeDao(BaseDao):
    async def get_by_code(self, code: str) -> Optional[OAuth2AuthorizationCode]:
        return await BaseDao.get_first(
            self,
            OAuth2AuthorizationCode,
            where=[OAuth2AuthorizationCode.code == code],
        )

    async def save(self, authorization_code: OAuth2AuthorizationCode) -> bool:
        authorization_code.updated_at = get_local_now()
        return await BaseDao.save(self, authorization_code)

    async def delete(self, authorization_code: OAuth2AuthorizationCode) -> bool:
        return await BaseDao.delete_by_id(
            self, OAuth2AuthorizationCode, authorization_code.code_id
        )


class OAuth2TokenDao(BaseDao):
    async def get_by_access_token(self, access_token: str) -> Optional[OAuth2Token]:
        return await BaseDao.get_first(
            self,
            OAuth2Token,
            where=[OAuth2Token.access_token == access_token],
        )

    async def get_by_refresh_token(
        self, refresh_token: str
    ) -> Optional[OAuth2Token]:
        return await BaseDao.get_first(
            self,
            OAuth2Token,
            where=[OAuth2Token.refresh_token == refresh_token],
        )

    async def save(self, token: OAuth2Token) -> bool:
        token.updated_at = get_local_now()
        return await BaseDao.save(self, token)


__all__ = [
    "OAuth2Client",
    "OAuth2ClientDao",
    "OAuth2AuthorizationCode",
    "OAuth2AuthorizationCodeDao",
    "OAuth2Token",
    "OAuth2TokenDao",
]
