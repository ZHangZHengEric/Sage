from __future__ import annotations

from app.v2.server.conversations.bindings import require_binding

from app.v2.server.catalog.records import (
    ModelRecord,
    UserCatalog,
    apply_delete,
    apply_upsert,
    empty_catalog,
    delete_agent,
    require_agent,
)
from app.v2.server.identity.key_repository import MemoryApiKeyStore  # noqa: F401
from app.v2.server.skills.repository import MemorySkillStore  # noqa: F401
from app.v2.server.conversations.records import (
    ThreadRecord,
    apply_thread_upsert,
    require_owned_thread,
)
from app.v2.server.identity.users import UserRecord


class MemoryUserStore:
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}

    async def list_users(self) -> list[UserRecord]:
        return list(self._users.values())

    async def get_by_username(self, username: str) -> UserRecord | None:
        needle = username.strip().lower()
        return next(
            (
                user
                for user in self._users.values()
                if user.username.lower() == needle
            ),
            None,
        )

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self._users.get(user_id)

    async def admin(self) -> UserRecord | None:
        return next(
            (user for user in self._users.values() if user.role == "admin"),
            None,
        )

    async def save(self, user: UserRecord) -> None:
        self._users[user.user_id] = user


class MemoryCatalogStore:
    def __init__(self) -> None:
        self._catalogs: dict[str, UserCatalog] = {}

    async def list_resources(self, user_ids, section):
        return [(user_id, item) for user_id in user_ids
                for item in getattr(self._catalogs.get(user_id) or empty_catalog(), section)]

    async def list_agent_summaries(self, user_ids):
        result = []
        for user_id in user_ids:
            catalog = await self.get(user_id)
            models = {model.id: model.model for model in catalog.models}
            for agent in catalog.agents:
                result.append(dict(
                    id=agent.id, user_id=user_id, name=agent.name,
                    description=agent.description, model_id=agent.model_id,
                    model_name=models.get(agent.model_id, agent.model_id),
                    tool_count=len(agent.tools), skill_count=len(agent.skills),
                ))
        return result

    async def agent_owner(self, agent_id):
        return next((uid for uid, catalog in self._catalogs.items()
                     if any(a.id == agent_id for a in catalog.agents)), None)

    async def get(self, user_id: str) -> UserCatalog:
        current = self._catalogs.get(user_id)
        if current is None:
            current = empty_catalog()
            self._catalogs[user_id] = current
        return current.model_copy(deep=True)

    async def save(self, user_id: str, catalog: UserCatalog) -> UserCatalog:
        self._catalogs[user_id] = catalog.model_copy(deep=True)
        return catalog

    async def replace_section(
        self, user_id: str, section: str, catalog: UserCatalog
    ) -> UserCatalog:
        current = self._catalogs.get(user_id) or empty_catalog()
        updated = current.model_copy(update={section: getattr(catalog, section)})
        self._catalogs[user_id] = updated
        return updated

    async def create_agent(self, user_id, record):
        catalog = await self.get(user_id)
        catalog.agents.append(record)
        await self.save(user_id, catalog)

    async def update_agent(self, user_id, record):
        catalog = await self.get(user_id)
        require_agent(catalog, record.id)
        catalog.agents = [record if a.id == record.id else a for a in catalog.agents]
        await self.save(user_id, catalog)

    async def delete_agent(self, user_id, agent_id):
        catalog = delete_agent(await self.get(user_id), agent_id)
        if catalog.default_agent_id == agent_id:
            catalog.default_agent_id = catalog.agents[0].id
        await self.save(user_id, catalog)

    async def list_models(self, user_id: str) -> list[ModelRecord]:
        return (await self.get(user_id)).models

    async def list_all_models(
        self, user_ids: list[str]
    ) -> list[tuple[str, ModelRecord]]:
        return [
            (user_id, model)
            for user_id in user_ids
            for model in await self.list_models(user_id)
        ]

    async def default_model(self, user_id: str) -> ModelRecord | None:
        models = await self.list_models(user_id)
        return next(
            (item for item in models if item.is_default),
            models[0] if models else None,
        )

    async def upsert_model(
        self, user_id: str, payload: dict[str, object]
    ) -> ModelRecord:
        record, catalog = apply_upsert(await self.get(user_id), payload)
        await self.replace_section(user_id, "models", catalog)
        return record

    async def delete_model(self, user_id: str, model_id: str) -> None:
        catalog = apply_delete(await self.get(user_id), model_id)
        await self.replace_section(user_id, "models", catalog)




class MemoryThreadIndex:
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._bindings = {}

    async def binding(self, session_id):
        return self._bindings.get(session_id)

    async def bind(self, binding):
        existing = self._bindings.setdefault(binding.session_id, binding)
        require_binding(existing, binding)

    async def list_all(self) -> list[ThreadRecord]:
        return sorted(
            self._threads.values(), key=lambda item: item.updated_at, reverse=True
        )

    async def list_for(self, user_id: str) -> list[ThreadRecord]:
        return sorted(
            (item for item in self._threads.values() if item.user_id == user_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    async def find(self, thread_id: str) -> ThreadRecord | None:
        return self._threads.get(thread_id)

    async def upsert(
        self,
        thread_id: str,
        user_id: str,
        *,
        title: str = "",
        agent_id: str | None = None,
    ) -> ThreadRecord:
        existing = self._threads.get(thread_id)
        record = apply_thread_upsert(
            existing,
            thread_id=thread_id,
            user_id=user_id,
            title=title,
            agent_id=agent_id,
        )
        self._threads[thread_id] = record
        return record

    async def remove(self, thread_id: str, user_id: str) -> None:
        require_owned_thread(self._threads.get(thread_id), user_id)
        del self._threads[thread_id]
