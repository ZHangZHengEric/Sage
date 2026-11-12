"""Owner-authorized history, bounded comparisons, rollback, and Agent pins."""
from dataclasses import replace
import difflib

from app.v2.server.skills.files import inspect_skill_directory, skill_io
from app.v2.server.skills.records import SkillRecord
from app.v2.server.skills.service import SkillCatalogService
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def _missing(message: str = "skill version not found") -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(code="skill.version_not_found",
        category=ErrorCategory.VALIDATION, message=message))


class SkillVersionService:
    def __init__(self, catalog: SkillCatalogService) -> None:
        self.catalog = catalog

    async def list(self, skill_id: str, *, user_id: str, role: str, limit: int = 50,
                   before_revision: int | None = None) -> list[SkillRecord]:
        await self.catalog.get(skill_id, user_id=user_id, role=role)
        records = await self.catalog.store.list_versions(skill_id,
            limit=min(max(limit, 1), 100), before_revision=before_revision)
        # Older databases did not snapshot descriptions. Recover from immutable
        # packages rather than displaying the current version's description.
        def metadata():
            return [replace(record, description=self._package(record).description)
                    if not record.description else record for record in records]
        return await skill_io(metadata)

    async def get(self, skill_id: str, version_id: str, *, user_id: str, role: str) -> SkillRecord:
        current = await self.catalog.get(skill_id, user_id=user_id, role=role)
        records = await self.catalog.store.get_versions([version_id])
        record = next((item for item in records if item.skill_id == skill_id
                       and item.owner_user_id == current.owner_user_id), None)
        if record is None:
            raise _missing()
        return record

    def _package(self, record: SkillRecord):
        package = inspect_skill_directory(record.absolute_path(self.catalog.data_root))
        if package.package_sha256 != record.package_sha256:
            raise _missing("skill version artifact has changed")
        return replace(package, name=record.name)

    async def content(self, skill_id: str, version_id: str, *, user_id: str, role: str):
        record = await self.get(skill_id, version_id, user_id=user_id, role=role)
        package = await skill_io(self._package, record)
        return {**record.public_dict(), "description": package.description,
                "content": package.files["SKILL.md"].decode("utf-8")}

    async def diff(self, skill_id: str, from_version: str, to_version: str, *, user_id: str, role: str):
        before = await self.get(skill_id, from_version, user_id=user_id, role=role)
        after = await self.get(skill_id, to_version, user_id=user_id, role=role)
        def compare():
            old, new = self._package(before).files, self._package(after).files
            changes, remaining = [], 256 * 1024
            for path in sorted(old.keys() | new.keys()):
                left, right = old.get(path, b""), new.get(path, b"")
                if path in old and path in new and left == right:
                    continue
                change = {"path": path, "status": "added" if path not in old else
                          "removed" if path not in new else "modified",
                          "binary": False, "truncated": False, "diff": ""}
                try:
                    if b"\0" in left or b"\0" in right:
                        raise UnicodeError()
                    a, b = left.decode("utf-8"), right.decode("utf-8")
                    if max(len(left), len(right)) > 32 * 1024 or max(len(a.splitlines()), len(b.splitlines())) > 2000:
                        change["truncated"] = True
                    else:
                        delta = "".join(difflib.unified_diff(a.splitlines(keepends=True),
                            b.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))
                        change["diff"] = delta[:remaining]
                        change["truncated"] = len(delta) > remaining
                        remaining -= len(change["diff"])
                except UnicodeError:
                    change["binary"] = True
                changes.append(change)
            return {"from_version_id": from_version, "to_version_id": to_version, "files": changes}
        return await skill_io(compare)

    async def rollback(self, skill_id: str, version_id: str, *, expected_version_id: str,
                       user_id: str, role: str) -> SkillRecord:
        record = await self.get(skill_id, version_id, user_id=user_id, role=role)
        package = await skill_io(self._package, record)
        return await self.catalog.publish_package(package, owner_user_id=record.owner_user_id,
            expected_version_id=expected_version_id, force_new_version=True)

    async def bind_version(self, agent_id: str, skill_id: str, version_id: str | None,
                           *, user_id: str) -> SkillRecord:
        current = await self.catalog.get(skill_id, user_id=user_id, role="user")
        if version_id is not None:
            await self.get(skill_id, version_id, user_id=user_id, role="user")
        set_version = getattr(self.catalog.store, "set_binding_version", None)
        if set_version is not None:
            if not await set_version(
                owner_user_id=user_id, agent_id=agent_id, skill_id=skill_id, version_id=version_id,
            ):
                raise _missing("bind this skill to the Agent before selecting a version")
        else:
            bindings = await self.catalog.store.list_bindings(owner_user_id=user_id, agent_id=agent_id)
            if not any(item.source_skill_id == skill_id for item in bindings):
                raise _missing("bind this skill to the Agent before selecting a version")
            await self.catalog.store.replace_bindings(owner_user_id=user_id, agent_id=agent_id,
                bindings=[replace(item, source_version_id=version_id)
                          if item.source_skill_id == skill_id else item for item in bindings])
        bound = await self.catalog.bound_skills(owner_user_id=user_id, agent_id=agent_id)
        result = next((item for item in bound if item.skill_id == current.skill_id), None)
        if result is None:
            raise _missing("Skill binding changed while selecting a version")
        return result
