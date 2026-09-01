"""Native filesystem Skill catalog/source with bounded, symlink-safe reads."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor


class FilesystemSkillProvider:
    """Discover direct child folders containing `SKILL.md`, then fetch lazily."""

    plugin_id = "sage.skill.filesystem"

    def __init__(
        self,
        roots: tuple[str | Path, ...],
        *,
        source_id: str = "filesystem",
        max_files: int = 2_000,
        max_total_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        self.source_id = source_id
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes

    def descriptors(self) -> dict[str, SkillDescriptor]:
        values: dict[str, SkillDescriptor] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for candidate in sorted(root.iterdir()):
                skill_file = candidate / "SKILL.md"
                if (
                    not candidate.is_dir()
                    or candidate.is_symlink()
                    or not skill_file.is_file()
                    or skill_file.is_symlink()
                ):
                    continue
                description = self._description(skill_file)
                values[candidate.name] = SkillDescriptor(
                    name=candidate.name,
                    description=description,
                    source_id=self.source_id,
                )
        return values

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        values = self.descriptors()
        return tuple(values[name] for name in sorted(values))

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        try:
            return self.descriptors()[name]
        except KeyError as exc:
            raise self._error(
                "skill.not_found", f"skill {name!r} is not registered"
            ) from exc

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        descriptor = await self.get_skill(name, run_id=run_id)
        root = self._skill_root(name)
        files: dict[str, bytes] = {}
        total = 0
        for candidate in sorted(root.rglob("*")):
            if any(part in {"__pycache__", "node_modules"} for part in candidate.parts):
                continue
            if candidate.is_symlink():
                raise self._error(
                    "skill.symlink_denied", f"skill contains a symlink: {candidate}"
                )
            if not candidate.is_file():
                continue
            content = candidate.read_bytes()
            total += len(content)
            if len(files) + 1 > self.max_files or total > self.max_total_bytes:
                raise self._error(
                    "skill.bundle_too_large", "skill exceeds configured file limits"
                )
            files[candidate.relative_to(root).as_posix()] = content
        digest = hashlib.sha256()
        for path, content in files.items():
            digest.update(path.encode())
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
        return SkillBundle(
            descriptor=descriptor,
            files=files,
            content_hash=f"sha256:{digest.hexdigest()}",
        )

    def _skill_root(self, name: str) -> Path:
        for root in self.roots:
            candidate = (root / name).resolve()
            if candidate.parent == root and (candidate / "SKILL.md").is_file():
                return candidate
        raise self._error("skill.not_found", f"skill {name!r} is not registered")

    @staticmethod
    def _description(skill_file: Path) -> str:
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

        # A Skill's user-facing description belongs to its YAML front matter.
        # Parsing this single scalar locally keeps the provider dependency-free;
        # quoted values are handled without attempting to interpret arbitrary YAML.
        lines = text.splitlines()
        if lines and lines[0].strip() == "---":
            for line in lines[1:]:
                stripped = line.strip()
                if stripped == "---":
                    break
                key, separator, value = stripped.partition(":")
                if separator and key.strip() == "description":
                    return value.strip().strip("'\"")[:500]

        # Skills without front matter remain discoverable. Use the first heading
        # or prose line as a conservative fallback instead of exposing `name:`.
        body = lines
        if lines and lines[0].strip() == "---":
            closing = next(
                (
                    index
                    for index, line in enumerate(lines[1:], start=1)
                    if line.strip() == "---"
                ),
                len(lines) - 1,
            )
            body = lines[closing + 1 :]
        for line in body:
            stripped = line.strip().lstrip("#").strip()
            if stripped and not stripped.startswith("---"):
                return stripped[:500]
        return ""

    @staticmethod
    def _error(code: str, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )
