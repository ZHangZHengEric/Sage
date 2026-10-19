"""Remote files and a controlled Skills CLI adapter; no catalog writes here."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from urllib.parse import quote
import zipfile

from app.v2.server.skills.downloads import download_public_https, import_error, validate_https_url
from app.v2.server.skills.files import inspect_skill_directory, inspect_skill_zip, write_skill_package
from app.v2.server.skills.records import SkillPackage

SKILLS_CLI_VERSION = "1.7.2"
_MAX_FILES = 2000
_MAX_BYTES = 64 * 1024 * 1024
_IMPORT_SLOTS = threading.BoundedSemaphore(3)


@dataclass(frozen=True)
class CommandSource:
    repository: str
    ref: str = "HEAD"
    directory: str = ""
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedImport:
    revision: str
    packages: dict[str, SkillPackage]


def parse_skills_command(command: str) -> CommandSource:
    if any(c in command for c in ";&|<>`$\r\n\\"):
        raise import_error("仅支持 npx skills add 命令，不支持 Shell 表达式")
    try:
        args = shlex.split(command)
    except ValueError as exc:
        raise import_error("命令引号不完整") from exc
    if args[:2] in (["npx", "-y"], ["npx", "--yes"]):
        args.pop(1)
    if args[:3] != ["npx", "skills", "add"] or len(args) < 4:
        raise import_error("请输入 npx skills add <来源> [--skill 技能名]")
    source = args[3]
    selected: list[str] = []
    index = 4
    while index < len(args):
        arg = args[index]
        if arg in {"--yes", "-y", "--list", "-l"}:
            index += 1
            continue
        if arg not in {"--skill", "-s"}:
            raise import_error(f"不支持选项 {arg}；安装位置和目标由 Sage 管理")
        index += 1
        start = index
        while index < len(args) and not args[index].startswith("-"):
            selected.append(args[index])
            index += 1
        if index == start:
            raise import_error("--skill 后需要指定技能名")
    if not source.startswith("https://"):
        if "@" in source:
            source, inline_skill = source.rsplit("@", 1)
            selected.append(inline_skill)
        source = "https://github.com/" + source
    parts = validate_https_url(source)
    segments = parts.path.strip("/").split("/")
    if (
        parts.hostname != "github.com" or parts.query or len(segments) < 2
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", segments[0])
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", segments[1])
        or segments[0] in {".", ".."} or segments[1] in {".", ".."}
    ):
        raise import_error("Skills CLI 导入目前支持公开 GitHub 仓库或技能目录")
    repository = f"{segments[0]}/{segments[1].removesuffix('.git')}"
    ref, directory = "HEAD", ""
    if len(segments) > 2:
        if len(segments) < 4 or segments[2] != "tree":
            raise import_error("请输入 GitHub 仓库或 tree 目录地址")
        ref, directory = segments[3], "/".join(segments[4:])
        if any(part in {"", ".", ".."} for part in segments[3:]):
            raise import_error("GitHub 目录路径无效")
    if any(not name or len(name) > 192 for name in selected):
        raise import_error("技能名称无效")
    return CommandSource(repository, ref, directory, tuple(dict.fromkeys(selected)))


def inspect_archive(
    payload: bytes, *, directory: str = "", names: tuple[str, ...] = (),
) -> dict[str, SkillPackage]:
    """Discover one or more Skills while validating the entire ZIP before extraction."""
    if len(payload) > 32 * 1024 * 1024:
        raise import_error("ZIP 超过 32 MiB 限制")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries: dict[str, zipfile.ZipInfo] = {}
            total = 0
            infos = archive.infolist()
            if len(infos) > _MAX_FILES:
                raise import_error("ZIP 文件数量超过限制")
            for info in infos:
                path = info.filename.replace("\\", "/")
                parts = PurePosixPath(path).parts
                if (
                    path.startswith("/") or not parts or ".." in parts
                    or ":" in parts[0] or "\0" in path or len(parts) > 32
                ):
                    raise import_error("ZIP 包含不安全路径或特殊文件")
                normalized = "/".join(parts)
                if normalized in entries:
                    raise import_error("ZIP 包含重复文件路径")
                entries[normalized] = info
                total += info.file_size
                if total > _MAX_BYTES or info.file_size > _MAX_BYTES:
                    raise import_error("ZIP 解压内容超过 64 MiB 限制")
            for path in entries:
                if any(str(parent) in entries and not entries[str(parent)].is_dir()
                       for parent in PurePosixPath(path).parents):
                    raise import_error("ZIP 文件与目录路径冲突")
            roots = sorted(
                (str(PurePosixPath(path).parent) for path, info in entries.items()
                 if not info.is_dir() and PurePosixPath(path).name == "SKILL.md"),
                key=lambda item: (len(PurePosixPath(item).parts), item),
            )
            selected_roots: list[str] = []
            for root in roots:
                if directory:
                    relative = '/'.join(root.split('/')[1:])
                    if relative != directory and not relative.startswith(directory + '/'):
                        continue
                if not any(parent == "." or root.startswith(parent + "/") for parent in selected_roots):
                    selected_roots.append(root)
            if not selected_roots:
                raise import_error("ZIP 中未发现 SKILL.md")
            packages: dict[str, SkillPackage] = {}
            for root in selected_roots:
                prefix = "" if root == "." else root + "/"
                entry = entries[prefix + "SKILL.md"]
                if stat.S_IFMT(entry.external_attr >> 16) not in {0, stat.S_IFREG}:
                    raise import_error("技能包含不安全路径或特殊文件")
                if names and '*' not in names:
                    header = io.BytesIO()
                    with zipfile.ZipFile(header, "w", zipfile.ZIP_DEFLATED) as target:
                        target.writestr("SKILL.md", archive.read(entry))
                    descriptor = inspect_skill_zip(header.getvalue(), filename=PurePosixPath(root).name + ".zip")
                    if descriptor.name not in names:
                        continue
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
                    for path, info in entries.items():
                        if path.startswith(prefix):
                            if stat.S_IFMT(info.external_attr >> 16) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                                raise import_error("技能包含不安全路径或特殊文件")
                            if not info.is_dir():
                                target.writestr(path[len(prefix):], archive.read(info))
                package = inspect_skill_zip(buffer.getvalue(), filename=PurePosixPath(root).name + ".zip")
                if not names or '*' in names or package.name in names:
                    packages[root] = package
            if len(packages) > 32:
                raise import_error("一次最多导入 32 个技能，请指定技能目录或 --skill")
            return packages
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise import_error("ZIP 文件损坏或不受支持") from exc


def _run_skills_cli(packages: dict[str, SkillPackage], cache_root: Path) -> dict[str, SkillPackage]:
    npx = shutil.which("npx")
    if not npx:
        raise import_error("服务器未安装 Node.js / npx，无法使用 Skills CLI 导入")
    names = [package.name for package in packages.values()]
    if len(set(names)) != len(names):
        raise import_error("来源中存在同名技能，请指定具体技能目录")
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sage-skill-cli-") as temporary:
        root = Path(temporary)
        source, work, home = root / "source", root / "work", root / "home"
        work.mkdir()
        home.mkdir()
        # Feed only validated Skill bundles to the CLI, never remote commands or manifests.
        for package in packages.values():
            write_skill_package(source / "skills" / package.name, package)
        env = {
            "PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
            "TMPDIR": str(root), "CI": "1", "DO_NOT_TRACK": "1",
            "DISABLE_TELEMETRY": "1", "NO_COLOR": "1",
            "npm_config_cache": str(cache_root.resolve()),
            "npm_config_registry": "https://registry.npmjs.org",
            "npm_config_userconfig": str(home / ".npmrc"),
            "npm_config_globalconfig": str(home / "global-npmrc"),
            "npm_config_ignore_scripts": "true", "npm_config_offline": "false",
            "npm_config_audit": "false", "npm_config_fund": "false",
            "npm_config_fetch_retries": "0", "npm_config_fetch_timeout": "30000",
            "npm_config_update_notifier": "false",
        }
        args = [npx, "--yes", f"skills@{SKILLS_CLI_VERSION}", "add", str(source),
                "--agent", "universal", "--copy", "--yes", "--skill", "*"]
        process = subprocess.Popen(
            args, cwd=work, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            process.wait(timeout=90)
        except BaseException as exc:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            if isinstance(exc, subprocess.TimeoutExpired):
                raise import_error("Skills CLI 导入超时，请稍后重试") from exc
            raise
        if process.returncode:
            raise import_error("Skills CLI 运行失败，请检查 Node.js 版本及 npm registry 连接")
        installed = work / ".agents" / "skills"
        output: dict[str, SkillPackage] = {}
        for path, package in packages.items():
            actual = inspect_skill_directory(installed / package.name)
            if actual.package_sha256 != package.package_sha256:
                raise import_error("Skills CLI 输出与来源内容不一致")
            output[path] = actual
        return output


def prepare_import(kind: str, value: str, *, cache_root: Path, revision: str = "") -> PreparedImport:
    if not _IMPORT_SLOTS.acquire(blocking=False):
        raise import_error("正在处理其他技能导入，请稍后重试")
    try:
        if kind == "zip_url":
            payload = download_public_https(value)
            return PreparedImport(hashlib.sha256(payload).hexdigest(), inspect_archive(payload))
        if kind != "skills_cli":
            raise import_error("不支持的导入方式")
        source = parse_skills_command(value)
        if revision and not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise import_error("来源版本无效，请重新预览")
        if not revision:
            raw = download_public_https(
                f"https://api.github.com/repos/{source.repository}/commits/{quote(source.ref, safe='')}",
                max_bytes=1024 * 1024,
            )
            try:
                revision = json.loads(raw)["sha"]
            except (ValueError, KeyError, TypeError) as exc:
                raise import_error("无法解析 GitHub 仓库版本") from exc
            if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise import_error("GitHub 返回了无效版本")
        payload = download_public_https(f"https://codeload.github.com/{source.repository}/zip/{revision}")
        packages = inspect_archive(payload, directory=source.directory, names=source.skills)
        if source.skills and "*" not in source.skills:
            packages = {path: package for path, package in packages.items() if package.name in source.skills}
            if set(source.skills) != {package.name for package in packages.values()}:
                raise import_error("未找到命令指定的技能，请检查 --skill 名称")
        if not packages:
            raise import_error("指定目录中未发现技能")
        return PreparedImport(revision, _run_skills_cli(packages, cache_root))
    finally:
        _IMPORT_SLOTS.release()
