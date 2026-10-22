"""Explicit, content-pinned Skill grants for one Run and its delegation tree."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sagents.v2.contracts.runtime_skills import RuntimeSkillAttachment, RuntimeSkillAuthorization
from sagents.v2.contracts.errors import ErrorCategory
from sagents.v2.skill.bundles import skill_error
from sagents.v2.skill.contracts import SkillBundle, SkillCatalog, SkillDescriptor, SkillSource

if TYPE_CHECKING:
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.runtime.session.contracts import SessionStore


def validate_authorizations(
    attachments: Sequence[RuntimeSkillAttachment],
    authorizations: Sequence[RuntimeSkillAuthorization],
) -> None:
    names = set()
    for value in attachments:
        if value.descriptor.name in names:
            raise skill_error("skill.runtime_conflict", "duplicate runtime Skill name")
        names.add(value.descriptor.name)
        bundle = value.bundle()
        if not any(
            grant.descriptor == value.descriptor
            and grant.content_hash == value.content_hash
            and (not grant.target_agent_ids or value.target_agent_id in grant.target_agent_ids)
            and sum(map(len, bundle.files.values())) <= grant.max_bytes
            for grant in authorizations
        ):
            raise skill_error("skill.runtime_denied", "runtime Skill exceeds host authorization", ErrorCategory.POLICY_DENIED)


def inherit_runtime_skills(
    command: StartRun, parent_command: StartRun | None,
    authorizations: Sequence[RuntimeSkillAuthorization],
) -> StartRun:
    """Admission freezes inheritance; explicit child inputs cannot replace it."""
    inherited = parent_command.config.skill_attachments if parent_command else ()
    additions = tuple(
        value.model_copy(update={"target_agent_id": value.target_agent_id or command.agent_id})
        for value in command.config.skill_attachments
    )
    # Delegation callers may forward the exact durable grant. No replacement,
    # widening of scope, or source substitution is allowed under the same name.
    values = list(inherited)
    for value in additions:
        if value not in values:
            values.append(value)
    validate_authorizations(values, authorizations)
    return command.model_copy(update={"config": command.config.model_copy(update={
        "skill_attachments": tuple(values),
    })})


async def active_runtime_skills(
    command: StartRun, store: SessionStore,
    authorizations: Sequence[RuntimeSkillAuthorization],
) -> tuple[RuntimeSkillAttachment, ...]:
    """Resolve subtree membership from durable ancestry, never name prefixes."""
    values = command.config.skill_attachments
    if not values:
        return ()
    validate_authorizations(values, authorizations)
    ancestors = {command.agent_id}
    parent_id = command.parent_run_id
    seen = set()
    while parent_id:
        if parent_id in seen:
            raise skill_error("skill.runtime_scope_invalid", "cyclic Run ancestry")
        seen.add(parent_id)
        parent = await store.get_start_command(parent_id)
        ancestors.add(parent.agent_id)
        parent_id = parent.parent_run_id
    return tuple(value for value in values if value.target_agent_id in ancestors)


class RuntimeSkillProvider:
    """Overlay explicitly authorized snapshots on an already filtered catalog."""

    def __init__(
        self, catalog: SkillCatalog, source: SkillSource, raw_catalog: SkillCatalog,
        attachments: Sequence[RuntimeSkillAttachment],
    ) -> None:
        self.catalog = catalog
        self.source = source
        self.raw_catalog = raw_catalog
        self.attachments = {value.descriptor.name: value for value in attachments}

    async def _check_conflicts(self, run_id: str) -> None:
        if self.attachments:
            existing = await self.raw_catalog.list_skills(run_id=run_id)
            if any(value.name in self.attachments for value in existing):
                raise skill_error("skill.runtime_conflict", "runtime Skill name conflicts with an existing source")

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        await self._check_conflicts(run_id)
        values = await self.catalog.list_skills(run_id=run_id)
        return (*values, *(value.descriptor for value in self.attachments.values()))

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        await self._check_conflicts(run_id)
        if name in self.attachments:
            return self.attachments[name].descriptor
        return await self.catalog.get_skill(name, run_id=run_id)

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        await self._check_conflicts(run_id)
        if name in self.attachments:
            return self.attachments[name].bundle()
        return await self.source.fetch(name, run_id=run_id)

    async def fetch_latest(self, name: str, *, run_id: str) -> SkillBundle:
        if name in self.attachments:
            return await self.fetch(name, run_id=run_id)
        fetch = getattr(self.source, "fetch_latest", self.source.fetch)
        return await fetch(name, run_id=run_id)
