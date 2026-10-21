"""Catalog use cases: one user's agents, models, MCP servers, and A2A peers."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager

from app.v2.server.catalog.records import (
    AgentRecord,
    ModelRecord,
    delete_a2a_agent,
    delete_mcp,
    require_agent,
    upsert_a2a_agent,
    upsert_agent,
    upsert_mcp,
)
from app.v2.server.runtime.integrations.a2a import discover_a2a_skills, to_a2a_config
from app.v2.server.runtime.integrations.mcp import discover_mcp_tools, to_mcp_config
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions import ExtensionRegistry


class CatalogService:
    def __init__(self, store, *, mcp_plugins, a2a_plugins, skills) -> None:
        self.store = store
        self.extensions: ExtensionRegistry | None = None
        self.locks = tuple(asyncio.Lock() for _ in range(64))
        self.mcp_plugins = mcp_plugins
        self.a2a_plugins = a2a_plugins
        self.skills = skills
        self._probe_slots = asyncio.Semaphore(4)
        self._probing_users: set[str] = set()

    async def agent_owner(self, agent_id: str) -> str | None:
        return await self.store.agent_owner(agent_id)

    async def get(self, user_id: str):
        return await self.store.get(user_id)

    async def get_for_run(self, user_id: str, agent_id: str | None = None):
        return await self.store.get_for_run(user_id, agent_id)

    async def editor_catalog(self, user_id: str):
        return await self.store.editor_catalog(user_id)

    async def get_execution_policy(self, user_id: str, agent_id: str):
        return await self.store.get_execution_policy(user_id, agent_id)

    async def list_agent_summaries(self, user_ids: list[str]) -> list[dict]:
        return await self.store.list_agent_summaries(user_ids)

    async def list_all_models(self, user_ids: list[str]):
        return await self.store.list_all_models(user_ids)

    async def list_resources(self, user_ids: list[str], section: str):
        return await self.store.list_resources(user_ids, section)

    @asynccontextmanager
    async def _lock(self, user_id: str, section: str):
        key = f"{user_id}\0{section}"
        index = int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") % len(
            self.locks
        )
        async with self.locks[index]:
            yield

    @asynccontextmanager
    async def model_probe_slot(self, user_id: str):
        if self._probe_slots.locked() or user_id in self._probing_users:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.model_probe.busy",
                    category=ErrorCategory.RATE_LIMITED,
                    message="模型能力探测正在进行，请稍后再试",
                )
            )
        async with self._probe_slots:
            self._probing_users.add(user_id)
            try:
                yield
            finally:
                self._probing_users.discard(user_id)

    async def upsert_model(self, user_id: str, payload: dict) -> ModelRecord:
        async with self._lock(user_id, "models"):
            return await self.store.upsert_model(user_id, payload)

    async def delete_model(self, user_id: str, model_id: str) -> None:
        async with self._lock(user_id, "models"):
            await self.store.delete_model(user_id, model_id)

    def _validate_agent_options(self, payload):
        budgets = payload.get("budgets") or {}
        if (budgets.get("max_steps") or 100) > 10000:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.catalog.validation",
                    category=ErrorCategory.VALIDATION,
                    message="max_steps exceeds host ceiling 10000",
                )
            )

    async def create_agent(self, user_id: str, payload: dict) -> AgentRecord:
        self._validate_agent_options(payload)
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            record, catalog = upsert_agent(catalog, {**payload, "id": new_id("agent")}, registry=self.extensions)
            await self.store.create_agent(user_id, record)
            return record

    async def get_agent(self, user_id: str, agent_id: str) -> dict:
        record = await self.store.get_agent(user_id, agent_id)
        payload = record.public_dict()
        payload["skills"] = list(await self.skills.bound_names(user_id, agent_id))
        return payload

    async def editor_resources(self, user_id: str) -> dict:
        catalog, skills = await asyncio.gather(
            self.store.editor_catalog(user_id),
            self.skills.list_visible(user_id=user_id, role="user"),
        )
        return {
            "models": [{"id": item.id, "model": item.model, "is_default": item.is_default}
                       for item in catalog.models],
            "skills": [{"skill_id": item.skill_id, "name": item.name, "description": item.description}
                       for item in skills],
            "external_tools": list(dict.fromkeys([
                *[name for server in catalog.mcp_servers if not server.disabled for name in server.tools],
                *[name for peer in catalog.a2a_agents if not peer.disabled for name in peer.skills],
            ])),
            "external_tool_groups": [
                *[{"source": "mcp", "name": server.name, "tools": list(server.tools)}
                  for server in catalog.mcp_servers if not server.disabled],
                *[{"source": "a2a", "name": peer.name, "tools": list(peer.skills)}
                  for peer in catalog.a2a_agents if not peer.disabled],
            ],
        }

    async def update_agent(
        self, user_id: str, agent_id: str, payload: dict
    ) -> AgentRecord:
        self._validate_agent_options(payload)
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            require_agent(catalog, agent_id)
            payload = {**payload, "id": agent_id}
            record, catalog = upsert_agent(catalog, payload, registry=self.extensions)
            await self.store.update_agent(user_id, record)
            return record

    async def update_agent_instructions(self, user_id: str, agent_id: str, instructions: str) -> AgentRecord:
        """Update one field while preserving current Agent configuration."""
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            current = require_agent(catalog, agent_id)
            if current.instructions == instructions:
                return current
            updated = current.with_configuration(instructions=instructions)
            await self.store.update_agent(user_id, updated)
            return updated

    async def delete_agent(self, user_id: str, agent_id: str) -> None:
        async with self._lock(user_id, "agents"):
            await self.store.delete_agent(user_id, agent_id)

    async def create_mcp(self, user_id: str, payload: dict):
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            record, _ = upsert_mcp(catalog, payload)
            await self.store.save_resource(user_id, "mcp_servers", record)
            return record

    async def update_mcp(self, user_id: str, name: str, payload: dict):
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            payload = {**payload, "name": name}
            record, _ = upsert_mcp(catalog, payload)
            await self.store.save_resource(user_id, "mcp_servers", record)
            return record

    async def delete_mcp(self, user_id: str, name: str) -> None:
        async with self._lock(user_id, "mcp_servers"):
            catalog = await self.store.get(user_id)
            delete_mcp(catalog, name)
            await self.store.delete_resource(user_id, "mcp_servers", name)

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
            await self.store.save_resource(user_id, "mcp_servers", record)
        self.mcp_plugins.invalidate(user_id)
        return record

    async def create_a2a_agent(self, user_id: str, payload: dict):
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            record, _ = upsert_a2a_agent(catalog, payload)
            await self.store.save_resource(user_id, "a2a_agents", record)
            return record

    async def update_a2a_agent(self, user_id: str, name: str, payload: dict):
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            payload = {**payload, "name": name}
            record, _ = upsert_a2a_agent(catalog, payload)
            await self.store.save_resource(user_id, "a2a_agents", record)
        self.a2a_plugins.invalidate(user_id)
        return record

    async def delete_a2a_agent(self, user_id: str, name: str) -> None:
        async with self._lock(user_id, "a2a_agents"):
            catalog = await self.store.get(user_id)
            delete_a2a_agent(catalog, name)
            await self.store.delete_resource(user_id, "a2a_agents", name)
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
            await self.store.save_resource(user_id, "a2a_agents", record)
        self.a2a_plugins.invalidate(user_id)
        return record

    async def bind_agent_skills(self, user_id: str, agent_id: str, names: list[str]):
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            require_agent(catalog, agent_id)
            skills = await self.skills.bind_agent_skills(
                owner_user_id=user_id,
                agent_id=agent_id,
                names=names,
                catalog=catalog,
            )
            current = require_agent(await self.store.get(user_id), agent_id)
            bound = [item.name for item in skills]
            if current.skills != bound:
                await self.store.update_agent(user_id, current.with_configuration(skills=bound))
            return skills
