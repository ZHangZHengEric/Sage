"""Stateless preview and selected import into the existing owner-scoped catalog."""

import asyncio
from collections import Counter

from app.v2.server.skills.downloads import import_error
from app.v2.server.skills.import_sources import prepare_import
from app.v2.server.skills.service import SkillCatalogService
from sagents.v2.contracts.errors import SageV2Error


class SkillImportService:
    def __init__(self, catalog: SkillCatalogService):
        self.catalog = catalog

    async def _prepare(self, source, revision=""):
        return await asyncio.to_thread(
            prepare_import, source.kind, source.value.strip(),
            cache_root=self.catalog.data_root / "runtime" / "skill-import-npm-cache",
            revision=revision if source.kind == "skills_cli" else "",
        )

    async def preview(self, source, *, user_id: str):
        prepared = await self._prepare(source)
        existing = {item.name: item for item in await self.catalog.list_visible(user_id=user_id, role="user")}
        counts = Counter(package.name for package in prepared.packages.values())
        if any(count > 1 for count in counts.values()):
            raise import_error("来源中存在同名技能，请指定具体技能目录")
        candidates = []
        for path, package in prepared.packages.items():
            current = existing.get(package.name)
            candidates.append({
                "path": path, "name": package.name, "description": package.description,
                "file_count": package.file_count, "total_bytes": package.total_bytes,
                "package_sha256": package.package_sha256,
                "expected_version_id": current.version_id if current else "",
                "status": ("new" if current is None else "unchanged"
                           if current.package_sha256 == package.package_sha256 else "conflict"),
            })
        return {"revision": prepared.revision, "candidates": candidates}

    async def publish(self, body, *, user_id: str):
        if len({item.path for item in body.items}) != len(body.items):
            raise import_error("不能重复选择同一个技能")
        prepared = await self._prepare(body, body.revision)
        if prepared.revision != body.revision:
            raise import_error("来源内容已变化，请重新预览", conflict=True)
        names = [prepared.packages[item.path].name for item in body.items if item.path in prepared.packages]
        if len(set(names)) != len(names):
            raise import_error("不能同时导入多个同名技能")
        existing = {item.name: item for item in await self.catalog.list_visible(user_id=user_id, role="user")}
        results, skills = [], []
        for selected in body.items:
            try:
                package = prepared.packages.get(selected.path)
                if package is None or package.package_sha256 != selected.package_sha256:
                    raise import_error("技能内容已变化，请重新预览", conflict=True)
                current = existing.get(package.name)
                if current and current.package_sha256 == package.package_sha256:
                    record = current
                    message = "内容相同，无需更新"
                else:
                    actual_version = current.version_id if current else ""
                    if actual_version != selected.expected_version_id:
                        raise import_error("技能已被其他操作更新，请重新预览", conflict=True)
                    if current and not selected.overwrite:
                        raise import_error("存在同名技能，请明确选择更新", conflict=True)
                    record = await self.catalog.publish_package(
                        package, owner_user_id=user_id, expected_version_id=actual_version,
                    )
                    message = f"技能 {record.name} 已导入"
                skills.append(record.public_dict())
                results.append({"filename": selected.path, "success": True, "message": message, "skill": record.public_dict()})
            except SageV2Error as exc:
                results.append({"filename": selected.path, "success": False, "message": exc.info.message, "skill": None})
        return {"results": results, "skills": skills, "success_count": len(skills), "failed_count": len(results) - len(skills)}
