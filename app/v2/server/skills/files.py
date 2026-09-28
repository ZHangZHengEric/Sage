"""Read and write skill packages. Domain records stay free of the filesystem."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
from pathlib import Path

import yaml

from sagents.v2.package.strict_yaml import load_unique_yaml

from app.v2.server.skills.records import SkillPackage, normalize_skill_name
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def inspect_skill_directory(source: Path) -> SkillPackage:
    root = Path(source)
    if not root.is_dir():
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="skill package directory does not exist",
            )
        )
    skill_md = root / "SKILL.md"
    if not skill_md.is_file() or skill_md.is_symlink():
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="skill package must contain SKILL.md",
            )
        )
    files: dict[str, bytes] = {}
    total = 0
    for candidate in sorted(root.rglob("*")):
        if any(part in {"__pycache__", "node_modules"} for part in candidate.parts):
            continue
        if candidate.is_symlink():
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.skills.files.validation",
                    category=ErrorCategory.VALIDATION,
                    message="skill package cannot contain symbolic links",
                )
            )
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative in {".skill-manifest.json", ".materialized-skill.json"}:
            continue
        content = candidate.read_bytes()
        if len(files) >= 2_000 or total + len(content) > 64 * 1024 * 1024:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.skills.files.validation",
                    category=ErrorCategory.VALIDATION,
                    message="skill package exceeds size limits",
                )
            )
        files[relative] = content
        total += len(content)
    return _package_from_files(files, fallback_name=root.name)


def inspect_skill_zip(payload: bytes, *, filename: str = "") -> SkillPackage:
    """Read one skill ZIP in memory. A wrapper folder around SKILL.md is allowed."""

    if not payload:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="zip is empty",
            )
        )
    if len(payload) > 32 * 1024 * 1024:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="zip exceeds size limits",
            )
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="invalid zip file",
            )
        ) from exc
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
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.skills.files.validation",
                        category=ErrorCategory.VALIDATION,
                        message="skill package exceeds size limits",
                    )
                )
            content = archive.read(info)
            if len(files) >= 2_000 or total + len(content) > 64 * 1024 * 1024:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.skills.files.validation",
                        category=ErrorCategory.VALIDATION,
                        message="skill package exceeds size limits",
                    )
                )
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
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.conflict",
                category=ErrorCategory.CONFLICT,
                message="skill artifact already exists",
            )
        )
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
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.conflict",
                category=ErrorCategory.CONFLICT,
                message="workspace skill already exists",
            )
        )
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
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.skills.files.validation",
                    category=ErrorCategory.VALIDATION,
                    message=f"unsafe path in zip: {filename!r}",
                )
            )
        return None
    if relative.startswith("/") or (len(relative) > 1 and relative[1] == ":"):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message=f"unsafe path in zip: {filename!r}",
            )
        )
    if relative in {".skill-manifest.json", ".materialized-skill.json"}:
        return None
    return "/".join(parts)


def _unwrap_zip_root(files: dict[str, bytes]) -> dict[str, bytes]:
    if "SKILL.md" in files:
        return files
    prefixes = {
        path[: -len("SKILL.md")] for path in files if path.endswith("/SKILL.md")
    }
    if len(prefixes) != 1:
        return files
    prefix = next(iter(prefixes))
    if not prefix or not all(path.startswith(prefix) for path in files):
        return files
    return {
        path[len(prefix) :]: body for path, body in files.items() if path[len(prefix) :]
    }


def _package_from_files(files: dict[str, bytes], *, fallback_name: str) -> SkillPackage:
    if "SKILL.md" not in files:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="skill package must contain SKILL.md",
            )
        )
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
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.skills.files.validation",
                category=ErrorCategory.VALIDATION,
                message="SKILL.md must be UTF-8",
            )
        ) from exc
    metadata, body = _skill_metadata(text)
    description = metadata.get("description")
    if isinstance(description, str):
        return description
    for line in body:
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _skill_metadata(text: str) -> tuple[dict, list[str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            try:
                metadata = load_unique_yaml("\n".join(lines[1:index]) + "\n")
            except (ValueError, yaml.YAMLError):
                metadata = None
            return (metadata if isinstance(metadata, dict) else {}), lines[index + 1 :]
    return {}, []


def _front_matter_name(skill_md: bytes) -> str:
    try:
        text = skill_md.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    metadata, _ = _skill_metadata(text)
    name = metadata.get("name")
    return name if isinstance(name, str) else ""


def _copytree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for candidate in sorted(source.rglob("*")):
        if candidate.is_symlink():
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.skills.files.validation",
                    category=ErrorCategory.VALIDATION,
                    message="skill package cannot contain symbolic links",
                )
            )
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
