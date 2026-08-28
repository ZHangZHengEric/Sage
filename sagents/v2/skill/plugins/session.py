"""Skill activation state stored in the selected SessionStore namespace."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sagents.v2.skill.contracts import LoadedSkill


class SessionDerivedSkillActivationRepository:
    """Keep loaded-Skill state beside its Run without a second database."""

    namespace = "skill-activation"

    def __init__(
        self,
        session_store,
        session_id_resolver: Callable[[str], Awaitable[str]],
    ) -> None:
        self.session_store = session_store
        self.session_id_resolver = session_id_resolver
        self._lock = asyncio.Lock()

    async def list_loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]:
        session_id = await self.session_id_resolver(run_id)
        value = await self.session_store.get_derived_state(
            session_id, self.namespace, run_id
        )
        return tuple(LoadedSkill.model_validate(item) for item in (value or ()))

    async def put_loaded(self, value: LoadedSkill) -> None:
        async with self._lock:
            current = {
                item.descriptor.name: item
                for item in await self.list_loaded(run_id=value.run_id)
            }
            current[value.descriptor.name] = value
            await self.replace_loaded(
                run_id=value.run_id, values=tuple(current.values())
            )

    async def replace_loaded(
        self, *, run_id: str, values: tuple[LoadedSkill, ...]
    ) -> None:
        session_id = await self.session_id_resolver(run_id)
        await self.session_store.put_derived_state(
            session_id,
            self.namespace,
            run_id,
            [value.model_dump(mode="json") for value in values],
        )
