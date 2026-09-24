"""Operator listings. Reads go through stores; thread events go through conversations."""

from __future__ import annotations


class AdminService:
    def __init__(self, *, users, threads, catalog, conversations) -> None:
        self.users = users
        self.threads = threads
        self.catalog = catalog
        self.conversations = conversations

    async def list_users(self) -> list[dict]:
        return [user.public_dict() for user in await self.users.list_users()]

    async def list_threads(self) -> list[dict]:
        threads = await self.threads.list_all()
        names = {user.user_id: user.username for user in await self.users.list_users()}
        return [
            {
                **item.model_dump(mode="json"),
                "username": names.get(item.user_id, item.user_id),
            }
            for item in threads
        ]

    async def list_models(self) -> list[dict]:
        users = await self.users.list_users()
        names = {user.user_id: user.username for user in users}
        return [
            {
                **model.public_dict(),
                "user_id": user_id,
                "username": names.get(user_id, user_id),
            }
            for user_id, model in await self.catalog.list_all_models(
                [user.user_id for user in users]
            )
        ]

    async def thread_events(self, thread_id: str, admin_id: str, *, limit: int, offset):
        return await self.conversations.events(
            thread_id, admin_id, limit=limit, offset=offset, admin=True
        )
