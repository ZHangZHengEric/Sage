from __future__ import annotations

from typing import Protocol

from app.server_v2.infrastructure.database import Database
from sqlalchemy import select

from app.server_v2.infrastructure.database.schema import ApiKeyRow
from app.server_v2.domain.api_keys import (
    ApiKeyRecord,
    issue_api_key,
    require_usable_key,
    revoke,
    split_token,
)
from app.server_v2.core.errors import ServerV2Error


class ApiKeyStore(Protocol):
    async def create(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        name: str = "",
        scopes: list[str] | None = None,
    ) -> tuple[ApiKeyRecord, str]: ...
    async def list_for(self, owner_user_id: str) -> list[ApiKeyRecord]: ...
    async def get(self, key_id: str) -> ApiKeyRecord | None: ...
    async def revoke(self, key_id: str, owner_user_id: str) -> ApiKeyRecord: ...
    async def authenticate(self, token: str) -> ApiKeyRecord: ...


class DatabaseApiKeyStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        name: str = "",
        scopes: list[str] | None = None,
    ) -> tuple[ApiKeyRecord, str]:
        record, token = issue_api_key(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            name=name,
            scopes=scopes,
        )
        await self._save(record)
        return record, token

    async def list_for(self, owner_user_id: str) -> list[ApiKeyRecord]:
        async with self.database.session() as session:
            rows = list(
                (
                    await session.execute(
                        select(ApiKeyRow).where(
                            ApiKeyRow.owner_user_id == owner_user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        return sorted(
            [_key_from_row(row) for row in rows],
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        async with self.database.session() as session:
            row = await session.get(ApiKeyRow, key_id)
        return None if row is None else _key_from_row(row)

    async def revoke(self, key_id: str, owner_user_id: str) -> ApiKeyRecord:
        existing = await self.get(key_id)
        if existing is None or existing.owner_user_id != owner_user_id:
            raise ServerV2Error("not_found", "api key not found")
        record = revoke(existing)
        await self._save(record)
        return record

    async def authenticate(self, token: str) -> ApiKeyRecord:
        return require_usable_key(*await _resolve(self, token))

    async def _save(self, record: ApiKeyRecord) -> None:
        async with self.database.transaction() as session:
            await session.merge(
                ApiKeyRow(
                    key_id=record.key_id,
                    owner_user_id=record.owner_user_id,
                    agent_id=record.agent_id,
                    name=record.name,
                    key_hash=record.key_hash,
                    scopes=" ".join(record.scopes),
                    created_at=record.created_at,
                    revoked_at=record.revoked_at,
                )
            )


async def _resolve(store: ApiKeyStore, token: str) -> tuple[ApiKeyRecord | None, str]:
    """Split a presented token and load the record it names.

    A malformed token is reported as a missing record rather than its own
    error, so an attacker cannot tell a bad format from an unknown key id.
    """

    parsed = split_token(token)
    if parsed is None:
        return None, ""
    key_id, secret = parsed
    return await store.get(key_id), secret


class MemoryApiKeyStore:
    """Process-local keys, for deployments and tests without a host database."""

    def __init__(self) -> None:
        self._keys: dict[str, ApiKeyRecord] = {}

    async def create(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        name: str = "",
        scopes: list[str] | None = None,
    ) -> tuple[ApiKeyRecord, str]:
        record, token = issue_api_key(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            name=name,
            scopes=scopes,
        )
        self._keys[record.key_id] = record
        return record, token

    async def list_for(self, owner_user_id: str) -> list[ApiKeyRecord]:
        return sorted(
            (
                item
                for item in self._keys.values()
                if item.owner_user_id == owner_user_id
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        return self._keys.get(key_id)

    async def revoke(self, key_id: str, owner_user_id: str) -> ApiKeyRecord:
        existing = self._keys.get(key_id)
        if existing is None or existing.owner_user_id != owner_user_id:
            raise ServerV2Error("not_found", "api key not found")
        record = revoke(existing)
        self._keys[key_id] = record
        return record

    async def authenticate(self, token: str) -> ApiKeyRecord:
        return require_usable_key(*await _resolve(self, token))


def _key_from_row(row: ApiKeyRow) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id=row.key_id,
        owner_user_id=row.owner_user_id,
        agent_id=row.agent_id or "",
        name=row.name or "",
        key_hash=row.key_hash,
        scopes=[item for item in (row.scopes or "").split(" ") if item],
        created_at=row.created_at,
        revoked_at=row.revoked_at or "",
    )
