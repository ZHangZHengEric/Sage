from __future__ import annotations

import hashlib
from pathlib import Path

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import AgentRecord, UserCatalog
from app.server_v2.domain.skills import (
    AgentSkillBinding,
    SkillDimension,
    SkillPackage,
    SkillRecord,
    artifact_relative_path,
    copy_skill_tree,
    inspect_skill_directory,
    inspect_skill_markdown,
    new_skill_id,
    new_version_id,
    normalize_skill_name,
    normalize_skill_names,
    package_sha256_of,
    pick_visible_skill,
    resolve_artifact_path,
    resolve_bound_skills,
    workspace_skill_path,
    write_skill_package,
)
from app.server_v2.repositories.skills import SkillStore


class SkillCatalogService:
    """Publish, bind, and resolve Skills. Artifacts live under data_root/skills."""

    def __init__(self, store: SkillStore, data_root: Path) -> None:
        self.store = store
        self.data_root = Path(data_root)

    async def list_visible(
        self,
        *,
        user_id: str,
        role: str,
        dimension: SkillDimension | None = None,
    ) -> list[SkillRecord]:
        return await self.store.list_visible(
            user_id=user_id, role=role, dimension=dimension
        )

    async def get(self, skill_id: str, *, user_id: str, role: str) -> SkillRecord:
        record = await self.store.get(skill_id)
        if record is None or not _can_see(record, user_id=user_id, role=role):
            raise ServerV2Error("not_found", "skill not found")
        return record

    async def publish_markdown(
        self,
        *,
        name: str,
        content: str,
        user_id: str,
        role: str,
        dimension: SkillDimension = "user",
    ) -> SkillRecord:
        if dimension == "system" and role != "admin":
            raise ServerV2Error("forbidden", "only admin can publish system skills")
        package = inspect_skill_markdown(name=name, content=content)
        return await self._publish_package(
            package,
            dimension=dimension,
            owner_user_id="" if dimension == "system" else user_id,
        )

    async def publish_directory(
        self,
        source: Path,
        *,
        user_id: str,
        role: str,
        dimension: SkillDimension = "user",
    ) -> SkillRecord:
        if dimension == "system" and role != "admin":
            raise ServerV2Error("forbidden", "only admin can publish system skills")
        package = inspect_skill_directory(source)
        return await self._publish_package(
            package,
            dimension=dimension,
            owner_user_id="" if dimension == "system" else user_id,
        )

    async def update_content(
        self, skill_id: str, content: str, *, user_id: str, role: str
    ) -> SkillRecord:
        current = await self.get(skill_id, user_id=user_id, role=role)
        if current.dimension == "system" and role != "admin":
            raise ServerV2Error("forbidden", "only admin can edit system skills")
        if current.dimension == "user" and current.owner_user_id != user_id and role != "admin":
            raise ServerV2Error("forbidden", "skill not found")
        package = inspect_skill_markdown(name=current.name, content=content)
        if package.name != current.name:
            raise ServerV2Error("validation", "skill name cannot be changed")
        source = current.absolute_path(self.data_root)
        if source.is_dir():
            files = dict(inspect_skill_directory(source).files)
            files["SKILL.md"] = package.files["SKILL.md"]
            package = _package_from_files(
                name=current.name,
                description=package.description,
                files=files,
            )
        return await self._publish_package(
            package,
            dimension=current.dimension,
            owner_user_id=current.owner_user_id,
            skill_id=current.skill_id,
            revision=current.revision + 1,
        )

    async def disable(self, skill_id: str, *, user_id: str, role: str) -> None:
        current = await self.get(skill_id, user_id=user_id, role=role)
        if current.dimension == "system" and role != "admin":
            raise ServerV2Error("forbidden", "only admin can delete system skills")
        if current.dimension == "user" and current.owner_user_id != user_id and role != "admin":
            raise ServerV2Error("forbidden", "skill not found")
        await self.store.disable(skill_id)

    async def bind_agent_skills(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        names: list[str],
        catalog: UserCatalog | None = None,
    ) -> list[SkillRecord]:
        ordered = normalize_skill_names(names)
        visible = await self.store.list_visible(user_id=owner_user_id, role="user")
        resolved: list[SkillRecord] = []
        bindings: list[AgentSkillBinding] = []
        for position, name in enumerate(ordered):
            match = pick_visible_skill(visible, name=name, user_id=owner_user_id)
            if match is None:
                raise ServerV2Error("validation", f"unknown skill: {name}")
            resolved.append(match)
            bindings.append(
                AgentSkillBinding(
                    owner_user_id=owner_user_id,
                    agent_id=agent_id,
                    skill_name=name,
                    source_skill_id=match.skill_id,
                    position=position,
                )
            )
        await self.store.replace_bindings(
            owner_user_id=owner_user_id, agent_id=agent_id, bindings=bindings
        )
        if catalog is not None:
            _sync_agent_skills(catalog, agent_id, ordered)
        return resolved

    async def bound_skills(self, *, owner_user_id: str, agent_id: str) -> list[SkillRecord]:
        visible = await self.store.list_visible(user_id=owner_user_id, role="user")
        bindings = await self.store.list_bindings(
            owner_user_id=owner_user_id, agent_id=agent_id
        )
        return resolve_bound_skills(visible, bindings)

    async def bound_names(self, owner_user_id: str, agent_id: str) -> tuple[str, ...]:
        return tuple(
            item.name
            for item in await self.bound_skills(
                owner_user_id=owner_user_id, agent_id=agent_id
            )
        )

    async def read_content(self, skill_id: str, *, user_id: str, role: str) -> str:
        record = await self.get(skill_id, user_id=user_id, role=role)
        skill_md = record.absolute_path(self.data_root) / "SKILL.md"
        if not skill_md.is_file():
            raise ServerV2Error("not_found", "skill artifact is missing")
        return skill_md.read_text(encoding="utf-8")

    async def write_workspace_skill(
        self, *, user_id: str, name: str, content: str
    ) -> Path:
        """Copy-on-write into the tenant workspace. Catalog artifacts stay intact."""

        skill_name = normalize_skill_name(name)
        target = workspace_skill_path(self.data_root, user_id, skill_name)
        if not target.is_dir():
            source = await self._catalog_source(user_id, skill_name)
            if source is None:
                raise ServerV2Error("not_found", f"skill {skill_name!r} is not bound")
            copy_skill_tree(source, target)
        skill_md = target / "SKILL.md"
        inspect_skill_markdown(name=skill_name, content=content)
        skill_md.write_text(content if content.endswith("\n") else f"{content}\n", encoding="utf-8")
        return target

    async def workspace_status(self, *, user_id: str, name: str) -> str:
        target = workspace_skill_path(self.data_root, user_id, name)
        if not target.is_dir():
            return "missing"
        source = await self._catalog_source(user_id, name)
        if source is None:
            return "local"
        try:
            current = package_sha256_of(target)
            expected = package_sha256_of(source)
        except ServerV2Error:
            return "local"
        return "current" if current == expected else "modified"

    async def _catalog_source(self, user_id: str, name: str) -> Path | None:
        visible = await self.store.list_visible(user_id=user_id, role="user")
        match = pick_visible_skill(visible, name=name, user_id=user_id)
        if match is None:
            return None
        path = match.absolute_path(self.data_root)
        return path if path.is_dir() else None

    async def _publish_package(
        self,
        package: SkillPackage,
        *,
        dimension: SkillDimension,
        owner_user_id: str,
        skill_id: str | None = None,
        revision: int = 1,
    ) -> SkillRecord:
        visible = await self.store.list_visible(
            user_id=owner_user_id or "",
            role="admin" if dimension == "system" else "user",
            dimension=dimension,
        )
        existing = next(
            (
                item
                for item in visible
                if item.name == package.name and item.owner_user_id == owner_user_id
            ),
            None,
        )
        if existing is not None and existing.package_sha256 == package.package_sha256:
            return existing
        version_id = new_version_id()
        relative = artifact_relative_path(
            dimension=dimension,
            owner_user_id=owner_user_id,
            name=package.name,
            version_id=version_id,
        )
        destination = resolve_artifact_path(self.data_root, relative)
        write_skill_package(destination, package)
        record = SkillRecord(
            skill_id=skill_id or (existing.skill_id if existing is not None else new_skill_id()),
            version_id=version_id,
            revision=revision if existing is None else existing.revision + 1,
            dimension=dimension,
            owner_user_id=owner_user_id,
            name=package.name,
            description=package.description,
            artifact_path=relative,
            skill_md_sha256=package.skill_md_sha256,
            package_sha256=package.package_sha256,
            file_count=package.file_count,
            total_bytes=package.total_bytes,
        )
        return await self.store.publish(record)


def _can_see(record: SkillRecord, *, user_id: str, role: str) -> bool:
    if record.status != "active":
        return False
    if record.dimension == "system":
        return True
    return record.owner_user_id == user_id or role == "admin"


def _package_from_files(
    *, name: str, description: str, files: dict[str, bytes]
) -> SkillPackage:
    digest = hashlib.sha256()
    total = 0
    for relative, body in sorted(files.items()):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
        total += len(body)
    return SkillPackage(
        name=name,
        description=description,
        files=files,
        skill_md_sha256=hashlib.sha256(files["SKILL.md"]).hexdigest(),
        package_sha256=f"sha256:{digest.hexdigest()}",
        file_count=len(files),
        total_bytes=total,
    )


def _sync_agent_skills(catalog: UserCatalog, agent_id: str, names: list[str]) -> None:
    agents = list(catalog.agents)
    found = False
    for index, agent in enumerate(agents):
        if agent.id != agent_id:
            continue
        agents[index] = agent.model_copy(update={"skills": names})
        found = True
        break
    if not found:
        agents.append(AgentRecord(id=agent_id, name=agent_id, skills=names))
    catalog.agents = agents
