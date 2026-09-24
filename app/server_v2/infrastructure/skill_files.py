"""Read and write skill packages. Domain records stay free of the filesystem."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
from pathlib import Path

from app.server_v2.core.errors import ServerError
from app.server_v2.domain.skills import SkillPackage, normalize_skill_name


def inspect_skill_directory(source: Path) -> SkillPackage:
    root = Path(source)
    if not root.is_dir():
        raise ServerError("validation", "skill package directory does not exist")
    skill_md = root / "SKILL.md"
    if not skill_md.is_file() or skill_md.is_symlink():
        raise ServerError("validation", "skill package must contain SKILL.md")
    files: dict[str, bytes] = {}
    total = 0
    for candidate in sorted(root.rglob("*")):
        if any(part in {"__pycache__", "node_modules"} for part in candidate.parts):
            continue
        if candidate.is_symlink():
            raise ServerError("validation", "skill package cannot contain symbolic links")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative in {".skill-manifest.json", ".materialized-skill.json"}:
            continue
        content = candidate.read_bytes()
        if len(files) >= 2_000 or total + len(content) > 64 * 1024 * 1024:
            raise ServerError("validation", "skill package exceeds size limits")
        files[relative] = content
        total += len(content)
    return _package_from_files(files, fallback_name=root.name)


def inspect_skill_zip(payload: bytes, *, filename: str = "") -> SkillPackage:
    """Read one skill ZIP in memory. A wrapper folder around SKILL.md is allowed."""

    if not payload:
        raise ServerError("validation", "zip is empty")
    if len(payload) > 32 * 1024 * 1024:
        raise ServerError("validation", "zip exceeds size limits")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ServerError("validation", "invalid zip file") from exc
    files: dict[str, bytes] = {}
    total = 0
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_zip_path(info.filename)
            if relative is None:
                continue
            if info.file_size > 64 * 1024 * 1024:
                raise ServerError("validation", "skill package exceeds size limits")
            content = archive.read(info)
            if len(files) >= 2_000 or total + len(content) > 64 * 1024 * 1024:
                raise ServerError("validation", "skill package exceeds size limits")
            files[relative] = content
            total += len(content)
    files = _unwrap_zip_root(files)
    fallback = Path(filename or "skill").stem
    return _package_from_files(files, fallback_name=fallback)


def inspect_skill_markdown(*, name: str, content: str) -> SkillPackage:
    body = content if content.endswith("\n") else f"{content}\n"
    encoded = body.encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"SKILL.md\0")
    digest.update(encoded)
    digest.update(b"\0")
    return SkillPackage(
        name=normalize_skill_name(name),
        description=_description(encoded),
        files={"SKILL.md": encoded},
        skill_md_sha256=hashlib.sha256(encoded).hexdigest(),
        package_sha256=f"sha256:{digest.hexdigest()}",
        file_count=1,
        total_bytes=len(encoded),
    )


def write_skill_package(destination: Path, package: SkillPackage) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ServerError("conflict", "skill artifact already exists")
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        _rmtree(staging)
    staging.mkdir(parents=True)
    try:
        for relative, content in package.files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        staging.replace(destination)
    except Exception:
        _rmtree(staging)
        raise


def copy_skill_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ServerError("conflict", "workspace skill already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        _rmtree(staging)
    _copytree(source, staging)
    staging.replace(destination)


def package_sha256_of(path: Path) -> str:
    return inspect_skill_directory(path).package_sha256


def _safe_zip_path(filename: str) -> str | None:
    relative = str(filename or "").replace("\\", "/")
    while relative.startswith("./"):
        relative = relative[2:]
    if not relative or relative.endswith("/"):
        return None
    parts = [part for part in relative.split("/") if part not in {"", "."}]
    if not parts:
        return None
    if parts[0] == "__MACOSX" or parts[-1] in {".DS_Store"}:
        return None
    if any(part in {"__pycache__", "node_modules", ".."} for part in parts):
        if ".." in parts:
            raise ServerError("validation", f"unsafe path in zip: {filename!r}")
        return None
    if relative.startswith("/") or (len(relative) > 1 and relative[1] == ":"):
        raise ServerError("validation", f"unsafe path in zip: {filename!r}")
    if relative in {".skill-manifest.json", ".materialized-skill.json"}:
        return None
    return "/".join(parts)


def _unwrap_zip_root(files: dict[str, bytes]) -> dict[str, bytes]:
    if "SKILL.md" in files:
        return files
    prefixes = {
        path[: -len("SKILL.md")]
        for path in files
        if path.endswith("/SKILL.md")
    }
    if len(prefixes) != 1:
        return files
    prefix = next(iter(prefixes))
    if not prefix or not all(path.startswith(prefix) for path in files):
        return files
    return {path[len(prefix) :]: body for path, body in files.items() if path[len(prefix) :]}


def _package_from_files(files: dict[str, bytes], *, fallback_name: str) -> SkillPackage:
    if "SKILL.md" not in files:
        raise ServerError("validation", "skill package must contain SKILL.md")
    digest = hashlib.sha256()
    total = 0
    for relative, content in sorted(files.items()):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        total += len(content)
    description = _description(files["SKILL.md"])
    name = _front_matter_name(files["SKILL.md"]) or fallback_name
    return SkillPackage(
        name=normalize_skill_name(name),
        description=description,
        files=files,
        skill_md_sha256=hashlib.sha256(files["SKILL.md"]).hexdigest(),
        package_sha256=f"sha256:{digest.hexdigest()}",
        file_count=len(files),
        total_bytes=total,
    )


def _description(skill_md: bytes) -> str:
    try:
        text = skill_md.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ServerError("validation", "SKILL.md must be UTF-8") from exc
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            stripped = line.strip()
            if stripped == "---":
                break
            key, separator, value = stripped.partition(":")
            if separator and key.strip() == "description":
                return value.strip().strip("'\"")[:500]
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
        if stripped:
            return stripped[:500]
    return ""


def _front_matter_name(skill_md: bytes) -> str:
    try:
        text = skill_md.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, separator, value = stripped.partition(":")
        if separator and key.strip() == "name":
            return value.strip().strip("'\"")
    return ""


def _copytree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for candidate in sorted(source.rglob("*")):
        if candidate.is_symlink():
            raise ServerError("validation", "skill package cannot contain symbolic links")
        relative = candidate.relative_to(source)
        target = destination / relative
        if candidate.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if candidate.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(candidate.read_bytes())
            os.chmod(target, stat.S_IMODE(candidate.stat().st_mode))


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    for candidate in sorted(path.rglob("*"), reverse=True):
        if candidate.is_dir() and not candidate.is_symlink():
            candidate.rmdir()
        else:
            candidate.unlink(missing_ok=True)
    if path.exists():
        path.rmdir()
