"""Catalog use cases: one user's agents, models, MCP servers, and A2A peers."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import (
    AgentRecord,
    ModelRecord,
    UserCatalog,
    delete_a2a_agent,
    delete_agent,
    delete_mcp,
    require_agent,
    upsert_a2a_agent,
    upsert_agent,
    upsert_mcp,
)
from app.server_v2.infrastructure.a2a_client import discover_a2a_skills, to_a2a_config
from app.server_v2.infrastructure.mcp import discover_mcp_tools, to_mcp_config


class CatalogService:
    def __init__(self, store, locks, *, mcp_plugins, a2a_plugins, skills) -> None:
        self.store = store
        self.locks = locks
        self.mcp_plugins = mcp_plugins
        self.a2a_plugins = a2a_plugins
        self.skills = skills

    @asynccontextmanager
    async def _lock(self, user_id: str):
        index = int.from_bytes(
            hashlib.sha256(user_id.encode()).digest()[:2], "big"
        ) % len(self.locks)
        async with self.locks[index]:
            yield

    async def get(self, user_id: str) -> UserCatalog:
        return await self.store.get(user_id)

    async def save(self, user_id: str, catalog: UserCatalog) -> UserCatalog:
        return await self.store.save(user_id, catalog)

    async def list_models(self, user_id: str) -> list[ModelRecord]:
        return await self.store.list_models(user_id)

    async def list_all_models(self, user_ids: list[str]):
        return await self.store.list_all_models(user_ids)

    async def default_model(self, user_id: str) -> ModelRecord | None:
        return await self.store.default_model(user_id)

    async def upsert_model(self, user_id: str, payload: dict) -> ModelRecord:
        async with self._lock(user_id):
            return await self.store.upsert_model(user_id, payload)

    async def delete_model(self, user_id: str, model_id: str) -> None:
        async with self._lock(user_id):
            await self.store.delete_model(user_id, model_id)

    async def list_agents(self, user_id: str) -> list[AgentRecord]:
        return (await self.store.get(user_id)).agents

    async def create_agent(self, user_id: str, payload: dict) -> AgentRecord:
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_agent(catalog, payload)
            await self.store.save(user_id, catalog)
            return record

    async def get_agent(self, user_id: str, agent_id: str) -> dict:
        catalog = await self.store.get(user_id)
        record = require_agent(catalog, agent_id)
        payload = record.public_dict()
        payload["skills"] = list(await self.skills.bound_names(user_id, agent_id))
        return payload

    async def update_agent(
        self, user_id: str, agent_id: str, payload: dict
    ) -> AgentRecord:
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            require_agent(catalog, agent_id)
            payload = {**payload, "id": agent_id}
            record, catalog = upsert_agent(catalog, payload)
            await self.store.save(user_id, catalog)
            return record

    async def delete_agent(self, user_id: str, agent_id: str) -> None:
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            await self.store.save(user_id, delete_agent(catalog, agent_id))

    async def list_mcp(self, user_id: str):
        return (await self.store.get(user_id)).mcp_servers

    async def create_mcp(self, user_id: str, payload: dict):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_mcp(catalog, payload)
            await self.store.save(user_id, catalog)
            return record

    async def update_mcp(self, user_id: str, name: str, payload: dict):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            payload = {**payload, "name": name}
            record, catalog = upsert_mcp(catalog, payload)
            await self.store.save(user_id, catalog)
            return record

    async def delete_mcp(self, user_id: str, name: str) -> None:
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            await self.store.save(user_id, delete_mcp(catalog, name))

    async def refresh_mcp(self, user_id: str, name: str):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            current = next(
                (item for item in catalog.mcp_servers if item.name == name), None
            )
            if current is None:
                raise ServerV2Error("not_found", "mcp server not found")
            tools = await discover_mcp_tools(to_mcp_config(current))
            record = current.model_copy(update={"tools": list(dict.fromkeys(tools))})
            catalog.mcp_servers = [
                record if item.name == name else item for item in catalog.mcp_servers
            ]
            await self.store.save(user_id, catalog)
        self.mcp_plugins.invalidate(user_id)
        return record

    async def list_a2a_agents(self, user_id: str):
        return (await self.store.get(user_id)).a2a_agents

    async def create_a2a_agent(self, user_id: str, payload: dict):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_a2a_agent(catalog, payload)
            await self.store.save(user_id, catalog)
            return record

    async def update_a2a_agent(self, user_id: str, name: str, payload: dict):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            payload = {**payload, "name": name}
            record, catalog = upsert_a2a_agent(catalog, payload)
            await self.store.save(user_id, catalog)
        self.a2a_plugins.invalidate(user_id)
        return record

    async def delete_a2a_agent(self, user_id: str, name: str) -> None:
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            await self.store.save(user_id, delete_a2a_agent(catalog, name))
        self.a2a_plugins.invalidate(user_id)

    async def refresh_a2a_agent(self, user_id: str, name: str):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            current = next(
                (item for item in catalog.a2a_agents if item.name == name), None
            )
            if current is None:
                raise ServerV2Error("not_found", "a2a agent not found")
            skills = await discover_a2a_skills(to_a2a_config(current))
            record = current.model_copy(
                update={"skills": list(dict.fromkeys(skills))}
            )
            catalog.a2a_agents = [
                record if item.name == name else item for item in catalog.a2a_agents
            ]
            await self.store.save(user_id, catalog)
        self.a2a_plugins.invalidate(user_id)
        return record

    async def bind_agent_skills(self, user_id: str, agent_id: str, names: list[str]):
        async with self._lock(user_id):
            catalog = await self.store.get(user_id)
            skills = await self.skills.bind_agent_skills(
                owner_user_id=user_id,
                agent_id=agent_id,
                names=names,
                catalog=catalog,
            )
            await self.store.save(user_id, catalog)
            return skills
