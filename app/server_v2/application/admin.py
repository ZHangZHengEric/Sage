"""Operator listings. Reads go through stores; thread events go through the host."""

from __future__ import annotations


class AdminService:
    def __init__(self, host) -> None:
        self.host = host

    async def list_users(self) -> list[dict]:
        return [user.public_dict() for user in await self.host.users.list_users()]

    async def list_threads(self) -> list[dict]:
        return [
            {
                **item.model_dump(mode="json"),
                "username": await self.host.username_for(item.user_id),
            }
            for item in await self.host.threads.list_all()
        ]

    async def list_models(self) -> list[dict]:
        users = await self.host.users.list_users()
        return [
            {
                **model.public_dict(),
                "user_id": user_id,
                "username": await self.host.username_for(user_id),
            }
            for user_id, model in await self.host.catalog.list_all_models(
                [user.user_id for user in users]
            )
        ]

    async def thread_events(self, thread_id: str, admin_id: str, *, limit: int, offset):
        return await self.host.conversations.events(
            thread_id, admin_id, limit=limit, offset=offset, admin=True
        )
