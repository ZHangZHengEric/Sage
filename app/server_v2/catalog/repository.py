from __future__ import annotations

from typing import Protocol

from app.server_v2.database import Database

from app.server_v2.catalog.orm import CatalogRow
from app.server_v2.catalog.records import (
    ModelRecord,
    UserCatalog,
    apply_delete,
    apply_upsert,
    catalog_payload,
    empty_catalog,
)

_SECTIONS = ("agents", "models", "mcp_servers", "a2a_agents")


class CatalogStore(Protocol):
    async def get(self, user_id: str) -> UserCatalog: ...
    async def save(self, user_id: str, catalog: UserCatalog) -> UserCatalog: ...
    async def replace_section(
        self, user_id: str, section: str, catalog: UserCatalog
    ) -> UserCatalog: ...
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
        return UserCatalog.model_validate(
            {
                "agents": row.agents or [],
                "models": row.models or [],
                "mcp_servers": row.mcp_servers or [],
                "a2a_agents": row.a2a_agents or [],
            }
        )

    async def save(self, user_id: str, catalog: UserCatalog) -> UserCatalog:
        stored = catalog
        for section in _SECTIONS:
            stored = await self.replace_section(user_id, section, catalog)
        return stored

    async def replace_section(
        self, user_id: str, section: str, catalog: UserCatalog
    ) -> UserCatalog:
        if section not in _SECTIONS:
            raise ValueError(f"unknown catalog section: {section}")
        documents = catalog_payload(catalog)
        async with self.database.transaction() as session:
            row = await session.get(CatalogRow, user_id)
            if row is None:
                session.add(
                    CatalogRow(
                        user_id=user_id,
                        agents=documents["agents"],
                        models=documents["models"],
                        mcp_servers=documents["mcp_servers"],
                        a2a_agents=documents["a2a_agents"],
                    )
                )
            else:
                setattr(row, section, documents[section])
        return catalog

    async def list_all_models(self, user_ids: list[str]) -> list[tuple[str, ModelRecord]]:
        return [
            (user_id, model)
            for user_id in user_ids
            for model in (await self.get(user_id)).models
        ]

    async def default_model(self, user_id: str) -> ModelRecord | None:
        models = (await self.get(user_id)).models
        return next((item for item in models if item.is_default), models[0] if models else None)

    async def upsert_model(self, user_id: str, payload: dict[str, object]) -> ModelRecord:
        record, catalog = apply_upsert(await self.get(user_id), payload)
        await self.replace_section(user_id, "models", catalog)
        return record

    async def delete_model(self, user_id: str, model_id: str) -> None:
        catalog = apply_delete(await self.get(user_id), model_id)
        await self.replace_section(user_id, "models", catalog)
