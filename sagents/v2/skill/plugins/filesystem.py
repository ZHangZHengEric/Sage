"""Native filesystem Skill catalog/source with bounded, symlink-safe reads."""

from __future__ import annotations

import hashlib
import os
import threading
import yaml
from collections import OrderedDict
from sagents.v2._concurrency import bounded_to_thread
from pathlib import Path

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor
from sagents.v2.package.strict_yaml import load_unique_yaml


class FilesystemSkillProvider:
    """Discover direct child folders containing `SKILL.md`, then fetch lazily."""

    plugin_id = "sage.skill.filesystem"
    name = "Filesystem Skill provider"
    description = "Lazy, bounded, symlink-safe Skill catalog and source."

    def __init__(
        self,
        roots: tuple[str | Path, ...],
        *,
        source_id: str = "filesystem",
        max_files: int = 2_000,
        max_total_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_files <= 0:
            raise ValueError("max_files must be positive")
        if max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        self.source_id = source_id
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self._description_cache = OrderedDict()
        self._cache_lock = threading.Lock()

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
                description = self._cached_description(skill_file)
                # Roots are an ordered precedence list. Keep discovery and
                # `_skill_root()` aligned so metadata and fetched bytes always
                # come from the same first matching bundle.
                values.setdefault(
                    candidate.name,
                    SkillDescriptor(
                        name=candidate.name,
                        description=description,
                        source_id=self.source_id,
                    ),
                )
        return values

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        values = await bounded_to_thread("skill-io", self.descriptors)
        return tuple(values[name] for name in sorted(values))

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        return await bounded_to_thread("skill-io", lambda: self._descriptor(name))

    def _descriptor(self, name: str) -> SkillDescriptor:
        root = self._skill_root(name)
        return SkillDescriptor(
            name=name,
            description=self._cached_description(root / "SKILL.md"),
            source_id=self.source_id,
        )

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        return await bounded_to_thread("skill-io", lambda: self._fetch(name))

    def _fetch(self, name: str) -> SkillBundle:
        descriptor = self._descriptor(name)
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
            if len(files) >= self.max_files:
                raise self._error(
                    "skill.bundle_too_large", "skill exceeds configured file limits"
                )
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as exc:
                raise self._error(
                    "skill.symlink_denied",
                    f"skill file resolves outside its root: {candidate}",
                ) from exc
            content = self._read_bounded(
                resolved,
                remaining=self.max_total_bytes - total,
            )
            total += len(content)
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
            lexical = root / name
            if lexical.is_symlink() or (lexical / "SKILL.md").is_symlink():
                continue
            candidate = lexical.resolve()
            if candidate.parent == root and (candidate / "SKILL.md").is_file():
                return candidate
        raise self._error("skill.not_found", f"skill {name!r} is not registered")

    def _cached_description(self, path):
        try:
            stat = path.stat()
        except OSError:
            return self._description(path)
        key = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        with self._cache_lock:
            if key in self._description_cache:
                self._description_cache.move_to_end(key)
                return self._description_cache[key]
        value = self._description(path)
        with self._cache_lock:
            self._description_cache[key] = value
            self._description_cache.move_to_end(key)
            while len(self._description_cache) > 2048:
                self._description_cache.popitem(last=False)
        return value

    @staticmethod
    def _description(skill_file: Path) -> str:
        # Read only front matter (or the first prose line), without truncating
        # metadata or loading the Skill body. Preserve multiline YAML scalars.
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(skill_file, flags)
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                first = stream.readline()
                if first.strip() == "---":
                    header = []
                    for line in stream:
                        if line.strip() in {"---", "..."}:
                            break
                        header.append(line)
                    else:
                        return ""
                    try:
                        metadata = load_unique_yaml("".join(header))
                    except (ValueError, yaml.YAMLError):
                        metadata = None
                    if isinstance(metadata, dict):
                        description = metadata.get("description")
                        if isinstance(description, str):
                            return description
                else:
                    value = first.strip().lstrip("#").strip()
                    if value:
                        return value
                for line in stream:
                    value = line.strip().lstrip("#").strip()
                    if value and not value.startswith("---"):
                        return value
        except (OSError, UnicodeDecodeError):
            return ""
        return ""

    @staticmethod
    def _read_bounded(path: Path, *, remaining: int, truncate: bool = False) -> bytes:
        if remaining < 0:
            raise FilesystemSkillProvider._error(
                "skill.bundle_too_large", "skill exceeds configured file limits"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise FilesystemSkillProvider._error(
                "skill.file_unreadable", f"skill file cannot be opened safely: {path}"
            ) from exc
        with os.fdopen(descriptor, "rb") as stream:
            content = stream.read(remaining + 1)
        if len(content) > remaining:
            if truncate:
                return content[:remaining]
            raise FilesystemSkillProvider._error(
                "skill.bundle_too_large", "skill exceeds configured file limits"
            )
        return content

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
