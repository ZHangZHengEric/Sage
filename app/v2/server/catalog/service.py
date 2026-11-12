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
        return await self._save_agent(user_id, new_id("agent"), payload, create=True)

    async def _save_agent(self, user_id, agent_id, payload, *, create=False):
        self._validate_agent_options(payload)
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            current = None if create else require_agent(catalog, agent_id)
            record, _ = upsert_agent(catalog, {**payload, "id": agent_id}, registry=self.extensions)
            settings = payload.get("skill_bindings")
            if settings is None:
                if current is None:
                    await self.store.create_agent(user_id, record)
                else:
                    await self._update_agent_revision(user_id, record, current)
                return record

            names = settings["names"]
            _, _, visible, limit = self._skill_visibility(record, names, settings)
            names, bindings = await self._prepare_skill_bindings(user_id, record, names)
            record = record.with_configuration(
                skills=names,
                skill_visibility={"default_visible_skills": visible, "default_visible_skills_limit": limit},
            )
            await self._save_agent_and_bindings(user_id, record, current, bindings)
            return record

    async def _update_agent_revision(self, user_id, record, current):
        from app.v2.server.catalog.repository import DatabaseCatalogStore

        if isinstance(self.store, DatabaseCatalogStore):
            await self.store.update_agent(
                user_id, record, expected_package_ref=current.package_bundle.content_hash,
            )
        else:
            await self.store.update_agent(user_id, record)

    async def _save_agent_and_bindings(self, user_id, record, current, bindings):
        from app.v2.server.catalog.repository import DatabaseCatalogStore
        from app.v2.server.skills.repository import DatabaseSkillStore, MemorySkillStore

        skill_store = self.skills.store
        args = {"owner_user_id": user_id, "agent_id": record.id, "bindings": bindings}
        if (isinstance(skill_store, DatabaseSkillStore)
                and isinstance(self.store, DatabaseCatalogStore)
                and skill_store.database is self.store.database):
            await skill_store.replace_bindings(
                **args, agent_record=record,
                expected_package_ref=current.package_bundle.content_hash if current else None,
            )
            return

        async def save():
            if current is None:
                await self.store.create_agent(user_id, record)
            else:
                await self._update_agent_revision(user_id, record, current)

        if isinstance(skill_store, MemorySkillStore):
            await skill_store.replace_bindings(**args, before_commit=save)
        else:
            previous = await skill_store.list_bindings(owner_user_id=user_id, agent_id=record.id)
            await skill_store.replace_bindings(**args)
            try:
                await save()
            except BaseException:
                await skill_store.replace_bindings(owner_user_id=user_id, agent_id=record.id, bindings=previous)
                raise

    async def get_agent(self, user_id: str, agent_id: str) -> dict:
        record = await self.store.get_agent(user_id, agent_id)
        payload = record.public_dict()
        from app.v2.server.skills.runtime import enabled_skill_names
        records = await self.skills.bound_skills(owner_user_id=user_id, agent_id=agent_id)
        payload["skills"] = list(enabled_skill_names(records, record.package_bundle))
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
        return await self._save_agent(user_id, agent_id, payload)

    async def update_agent_instructions(self, user_id: str, agent_id: str, instructions: str) -> AgentRecord:
        """Update one field while preserving current Agent configuration."""
        async with self._lock(user_id, "agents"):
            catalog = await self.store.get(user_id)
            current = require_agent(catalog, agent_id)
            if current.instructions == instructions:
                return current
            updated = current.with_configuration(instructions=instructions)
            await self._update_agent_revision(user_id, updated, current)
            return updated

    async def apply_rsi_package(self, user_id, agent_id, package, expected_ref):
        async with self._lock(user_id, "agents"):
            await self.store.compare_and_swap_package(user_id, agent_id, package, expected_ref)

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

    async def _prepare_skill_bindings(self, user_id, record, names):
        from app.v2.server.skills.records import normalize_skill_names

        ordered = normalize_skill_names(names)
        files = record.package_bundle.files
        packaged_names = frozenset(name for name in ordered if f"skills/{name}/SKILL.md" in files)
        bindings = await self.skills.prepare_agent_skill_bindings(
            user_id, record.id, ordered, packaged_names=packaged_names,
        )
        return ordered, bindings

    @staticmethod
    def _skill_visibility(current, names, skill_visibility):
        from app.v2.server.skills.records import normalize_skill_names
        from sagents.v2.package.manifest.agents import (
            DEFAULT_VISIBLE_SKILLS_LIMIT, validate_default_visible_skills,
        )

        definition = current.package_bundle.manifest.agents[current.id]
        visibility = dict(skill_visibility or {})
        bound_names = set(normalize_skill_names(names))
        visible = definition.default_visible_skills
        if "default_visible_skills" in visibility:
            visible = visibility["default_visible_skills"]
            if visible is not None:
                visible = tuple(normalize_skill_names(visible))
        elif visible is not None:
            visible = tuple(name for name in visible if name in bound_names)
        limit = visibility.get("default_visible_skills_limit", definition.default_visible_skills_limit)
        if limit is None:
            limit = DEFAULT_VISIBLE_SKILLS_LIMIT
        try:
            validate_default_visible_skills(visible, bound_names, limit)
        except ValueError as exc:
            raise SageV2Error(RuntimeErrorInfo(
                code="server.catalog.validation", category=ErrorCategory.VALIDATION,
                message=str(exc),
            )) from exc
        return definition, visibility, visible, limit

    async def bind_agent_skills(
        self, user_id: str, agent_id: str, names: list[str], *,
        skill_visibility: dict | None = None,
    ):
        async with self._lock(user_id, "agents"):
            current = require_agent(await self.store.get(user_id), agent_id)
            definition, visibility, visible, limit = self._skill_visibility(current, names, skill_visibility)
            from app.v2.server.catalog.repository import DatabaseCatalogStore
            from app.v2.server.skills.repository import DatabaseSkillStore, MemorySkillStore

            names, bindings = await self._prepare_skill_bindings(user_id, current, names)
            skill_store = self.skills.store
            binding_args = {"owner_user_id": user_id, "agent_id": agent_id, "bindings": bindings}

            if (isinstance(skill_store, DatabaseSkillStore)
                    and isinstance(self.store, DatabaseCatalogStore)
                    and skill_store.database is self.store.database):
                # Resolve omitted fields against the package held under the row lock.
                explicit_visibility = {}
                if "default_visible_skills" in visibility:
                    explicit_visibility["default_visible_skills"] = visible
                if "default_visible_skills_limit" in visibility:
                    explicit_visibility["default_visible_skills_limit"] = limit
                await skill_store.replace_bindings(
                    **binding_args, skill_visibility=explicit_visibility, configured_names=names,
                    expected_package_ref=current.package_bundle.content_hash,
                )
            else:
                async def save_package():
                    if (current.skills != names or visible != definition.default_visible_skills
                            or limit != definition.default_visible_skills_limit):
                        record = current.with_configuration(
                            skills=names, skill_visibility={
                                "default_visible_skills": visible,
                                "default_visible_skills_limit": limit,
                            },
                        )
                        await self._update_agent_revision(user_id, record, current)

                if isinstance(skill_store, MemorySkillStore):
                    await skill_store.replace_bindings(**binding_args, before_commit=save_package)
                else:
                    previous = await skill_store.list_bindings(owner_user_id=user_id, agent_id=agent_id)
                    await skill_store.replace_bindings(**binding_args)
                    try:
                        await save_package()
                    except BaseException:
                        await skill_store.replace_bindings(
                            owner_user_id=user_id, agent_id=agent_id, bindings=previous,
                        )
                        raise
            return await self.skills.bound_skills(owner_user_id=user_id, agent_id=agent_id)

    async def bind_agent_skill_version(self, user_id: str, agent_id: str, skill_id: str, version_id: str | None):
        from app.v2.server.skills.versions import SkillVersionService
        from app.v2.server.skills.agent_guidance import _lock as guidance_lock
        # Guidance takes the Agent sync lock before the catalog write lock.
        # Keep that order so a policy change cannot race a workspace sync.
        async with guidance_lock(self.skills.guidance_locks, (user_id, agent_id)):
            async with self._lock(user_id, "agents"):
                require_agent(await self.store.get(user_id), agent_id)
                return await SkillVersionService(self.skills).bind_version(
                    agent_id, skill_id, version_id, user_id=user_id)
