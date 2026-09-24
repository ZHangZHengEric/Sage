"""API key use cases. Issuing a key checks that the named Agent exists."""

from __future__ import annotations

from app.server_v2.catalog.records import require_agent


class CredentialService:
    def __init__(self, keys, catalog) -> None:
        self.keys = keys
        self.catalog = catalog

    async def create(self, *, user_id: str, agent_id: str | None, name: str, scopes):
        catalog = await self.catalog.store.get(user_id)
        agent = require_agent(catalog, agent_id or None)
        return await self.keys.create(
            owner_user_id=user_id,
            agent_id=agent.id,
            name=name,
            scopes=scopes,
        )
