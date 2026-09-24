"""Catalog use cases: one user's agents, models, MCP servers, and A2A peers."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager

from app.server_v2.catalog.records import (
    AgentRecord,
    ModelRecord,
    delete_a2a_agent,
    delete_agent,
    delete_mcp,
    require_agent,
    upsert_a2a_agent,
    upsert_agent,
    upsert_mcp,
)
from app.server_v2.runtime.integrations.a2a import discover_a2a_skills, to_a2a_config
from app.server_v2.runtime.integrations.mcp import discover_mcp_tools, to_mcp_config
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class CatalogService:
    def __init__(self, store, *, mcp_plugins, a2a_plugins, skills) -> None:
        self.store = store
        self.locks = tuple(asyncio.Lock() for _ in range(64))
        self.mcp_plugins = mcp_plugins
        self.a2a_plugins = a2a_plugins
        self.skills = skills

    async def get(self, user_id: str):
        return await self.store.get(user_id)

    async def list_all_models(self, user_ids: list[str]):
        return await self.store.list_all_models(user_ids)

    @asynccontextmanager
    async def _lock(self, user_id: str, section: str):
        key = f"{user_id}\0{section}"
        index = int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") % len(
            self.locks
        )
        async with self.locks[index]:
            yield

    async def upsert_model(self, user_id: str, payload: dict) -> ModelRecord:
        async with self._lock(user_id, "models"):
            return await self.store.upsert_model(user_id, payload)

    async def delete_model(self, user_id: str, model_id: str) -> None:
        async with self._lock(user_id, "models"):
            await self.store.delete_model(user_id, model_id)

    async def create_agent(self, user_id: str, payload: dict) -> AgentRecord:
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_agent(catalog, payload)
            await self.store.replace_section(user_id, "agents", catalog)
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
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            require_agent(catalog, agent_id)
            payload = {**payload, "id": agent_id}
            record, catalog = upsert_agent(catalog, payload)
            await self.store.replace_section(user_id, "agents", catalog)
            return record

    async def delete_agent(self, user_id: str, agent_id: str) -> None:
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            await self.store.replace_section(
                user_id, "agents", delete_agent(catalog, agent_id)
            )

    async def create_mcp(self, user_id: str, payload: dict):
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_mcp(catalog, payload)
            await self.store.replace_section(user_id, "mcp_servers", catalog)
            return record

    async def update_mcp(self, user_id: str, name: str, payload: dict):
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            payload = {**payload, "name": name}
            record, catalog = upsert_mcp(catalog, payload)
            await self.store.replace_section(user_id, "mcp_servers", catalog)
            return record

    async def delete_mcp(self, user_id: str, name: str) -> None:
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            await self.store.replace_section(
                user_id, "mcp_servers", delete_mcp(catalog, name)
            )

    async def refresh_mcp(self, user_id: str, name: str):
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            current = next(
                (item for item in catalog.mcp_servers if item.name == name), None
            )
            if current is None:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.catalog.service.not_found",
                        category=ErrorCategory.VALIDATION,
                        message="mcp server not found",
                    )
                )
            tools = await discover_mcp_tools(to_mcp_config(current))
            record = current.model_copy(update={"tools": list(dict.fromkeys(tools))})
            catalog.mcp_servers = [
                record if item.name == name else item for item in catalog.mcp_servers
            ]
            await self.store.replace_section(user_id, "mcp_servers", catalog)
        self.mcp_plugins.invalidate(user_id)
        return record

    async def create_a2a_agent(self, user_id: str, payload: dict):
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_a2a_agent(catalog, payload)
            await self.store.replace_section(user_id, "a2a_agents", catalog)
            return record

    async def update_a2a_agent(self, user_id: str, name: str, payload: dict):
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            payload = {**payload, "name": name}
            record, catalog = upsert_a2a_agent(catalog, payload)
            await self.store.replace_section(user_id, "a2a_agents", catalog)
        self.a2a_plugins.invalidate(user_id)
        return record

    async def delete_a2a_agent(self, user_id: str, name: str) -> None:
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            await self.store.replace_section(
                user_id, "a2a_agents", delete_a2a_agent(catalog, name)
            )
        self.a2a_plugins.invalidate(user_id)

    async def refresh_a2a_agent(self, user_id: str, name: str):
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            current = next(
                (item for item in catalog.a2a_agents if item.name == name), None
            )
            if current is None:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.catalog.service.not_found",
                        category=ErrorCategory.VALIDATION,
                        message="a2a agent not found",
                    )
                )
            skills = await discover_a2a_skills(to_a2a_config(current))
            record = current.model_copy(update={"skills": list(dict.fromkeys(skills))})
            catalog.a2a_agents = [
                record if item.name == name else item for item in catalog.a2a_agents
            ]
            await self.store.replace_section(user_id, "a2a_agents", catalog)
        self.a2a_plugins.invalidate(user_id)
        return record

    async def bind_agent_skills(self, user_id: str, agent_id: str, names: list[str]):
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            skills = await self.skills.bind_agent_skills(
                owner_user_id=user_id,
                agent_id=agent_id,
                names=names,
                catalog=catalog,
            )
            await self.store.replace_section(user_id, "agents", catalog)
            return skills
