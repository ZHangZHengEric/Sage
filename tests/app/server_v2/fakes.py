from __future__ import annotations

from app.server_v2.domain.catalog import (
    ModelRecord,
    UserCatalog,
    apply_delete,
    apply_upsert,
    empty_catalog,
)
from app.server_v2.repositories.skills import MemorySkillStore
from app.server_v2.domain.threads import ThreadRecord, require_owned_thread
from app.server_v2.domain.users import (
    Role,
    UserRecord,
    build_user_record,
    reject_duplicate_username,
    reject_second_admin,
    require_valid_password,
)


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

    async def create(
        self, username: str, password: str, *, role: Role = "user"
    ) -> UserRecord:
        record = build_user_record(username, password, role=role)
        reject_duplicate_username(await self.get_by_username(record.username))
        reject_second_admin(role, await self.admin())
        self._users[record.user_id] = record
        return record

    async def ensure_admin(self, username: str, password: str) -> UserRecord:
        existing = await self.admin()
        if existing is not None:
            return existing
        named = await self.get_by_username(username)
        if named is not None:
            upgraded = UserRecord(
                user_id=named.user_id,
                username=named.username,
                password_hash=named.password_hash,
                role="admin",
            )
            self._users[named.user_id] = upgraded
            return upgraded
        return await self.create(username, password, role="admin")

    async def authenticate(self, username: str, password: str) -> UserRecord:
        return require_valid_password(await self.get_by_username(username), password)


class MemoryCatalogStore:
    def __init__(self) -> None:
        self._catalogs: dict[str, UserCatalog] = {}

    async def get(self, user_id: str) -> UserCatalog:
        return self._catalogs.get(user_id) or empty_catalog()

    async def save(self, user_id: str, catalog: UserCatalog) -> UserCatalog:
        self._catalogs[user_id] = catalog
        return catalog

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
        await self.save(user_id, catalog)
        return record

    async def delete_model(self, user_id: str, model_id: str) -> None:
        await self.save(user_id, apply_delete(await self.get(user_id), model_id))


class MemoryThreadIndex:
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}

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
        self, thread_id: str, user_id: str, *, title: str = ""
    ) -> ThreadRecord:
        existing = self._threads.get(thread_id)
        if existing is not None:
            require_owned_thread(existing, user_id)
        record = ThreadRecord(
            thread_id=thread_id,
            user_id=user_id,
            title=title or (existing.title if existing else title),
        )
        self._threads[thread_id] = record
        return record

    async def remove(self, thread_id: str, user_id: str) -> None:
        require_owned_thread(self._threads.get(thread_id), user_id)
        del self._threads[thread_id]
