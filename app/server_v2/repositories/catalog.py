from __future__ import annotations

from typing import Protocol

from app.server_v2.core.database import Database

from app.server_v2.db.models import CatalogRow
from app.server_v2.domain.catalog import (
    ModelRecord,
    UserCatalog,
    apply_delete,
    apply_upsert,
    catalog_payload,
    empty_catalog,
)


class CatalogStore(Protocol):
    async def list_models(self, user_id: str) -> list[ModelRecord]: ...
    async def list_all_models(
        self, user_ids: list[str]
    ) -> list[tuple[str, ModelRecord]]: ...
    async def default_model(self, user_id: str) -> ModelRecord | None: ...
    async def upsert_model(
        self, user_id: str, payload: dict[str, object]
    ) -> ModelRecord: ...
    async def delete_model(self, user_id: str, model_id: str) -> None: ...


class DatabaseCatalogStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, user_id: str) -> UserCatalog:
        async with self.database.session() as session:
            row = await session.get(CatalogRow, user_id)
        if row is None:
            return empty_catalog()
        return UserCatalog.model_validate(row.payload)

    async def save(self, user_id: str, catalog: UserCatalog) -> UserCatalog:
        async with self.database.transaction() as session:
            await session.merge(
                CatalogRow(user_id=user_id, payload=catalog_payload(catalog))
            )
        return catalog

    async def list_models(self, user_id: str) -> list[ModelRecord]:
        return (await self.get(user_id)).models

    async def list_all_models(self, user_ids: list[str]) -> list[tuple[str, ModelRecord]]:
        return [
            (user_id, model)
            for user_id in user_ids
            for model in await self.list_models(user_id)
        ]

    async def default_model(self, user_id: str) -> ModelRecord | None:
        models = await self.list_models(user_id)
        return next((item for item in models if item.is_default), models[0] if models else None)

    async def upsert_model(self, user_id: str, payload: dict[str, object]) -> ModelRecord:
        record, catalog = apply_upsert(await self.get(user_id), payload)
        await self.save(user_id, catalog)
        return record

    async def delete_model(self, user_id: str, model_id: str) -> None:
        await self.save(user_id, apply_delete(await self.get(user_id), model_id))
