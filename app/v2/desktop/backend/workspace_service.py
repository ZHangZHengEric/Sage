from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from app.v2.desktop.backend.service import DesktopV2Service

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any, Literal


from app.v2.desktop.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    stable_component_id as _stable_component_id,
)
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.skill import (
    FilesystemSkillProvider,
)
from sagents.v2.skill.contracts import SkillDescriptor
from app.v2.desktop.backend.schemas import (
    AgentCreate as AgentCreate,
    AgentSettingsPatch as AgentSettingsPatch,
    ComponentSelectionRequest as ComponentSelectionRequest,
    DesktopProject,
    DesktopRunRequest as DesktopRunRequest,
    DesktopV2Settings,
    ModelProviderCreate as ModelProviderCreate,
    ModelProviderPatch as ModelProviderPatch,
)
from app.v2.desktop.backend.run_context import (
    AgentRosterContextProvider as AgentRosterContextProvider,
)
from app.v2.desktop.backend.runtime_config import (
    _AGENT_ID,
    _SKILL_NAME,
    _resolved_sandbox_config,
    _sandbox_workspace_root,
)
from app.v2.desktop.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)
from app.v2.desktop.backend.settings_store import read_desktop_settings

_TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".csv",
    ".dart",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".log",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}


class DesktopWorkspaceServiceMixin:
    """Desktop settings, projects, workspace paths, and file projections."""

    _settings_cache_mtime: float | None

    async def get_settings(self) -> DesktopV2Settings:
        self = cast("DesktopV2Service", self)
        async with self._settings_lock:
            value = read_desktop_settings(self.settings_path)
        return value.model_copy(
            update={
                "agent_workspace_path": str(
                    self._agent_workspace_path(value.agent_workspace_path)
                )
            }
        )

    def _read_settings_sync(self) -> DesktopV2Settings:
        self = cast("DesktopV2Service", self)
        if not self.settings_path.exists():
            self._settings_cache = DesktopV2Settings()
            self._settings_cache_mtime = None
            return self._settings_cache
        mtime = self.settings_path.stat().st_mtime
        cached = getattr(self, "_settings_cache", None)
        if cached is not None and getattr(self, "_settings_cache_mtime", None) == mtime:
            return cached
        settings = read_desktop_settings(self.settings_path)
        self._settings_cache = settings
        self._settings_cache_mtime = self.settings_path.stat().st_mtime
        return settings

    async def save_settings(self, value: DesktopV2Settings) -> DesktopV2Settings:
        self = cast("DesktopV2Service", self)
        async with self._settings_update_lock:
            return await self._save_settings_unlocked(value)

    async def patch_settings(self, patch: dict[str, Any]) -> DesktopV2Settings:
        self = cast("DesktopV2Service", self)
        unknown = set(patch) - set(DesktopV2Settings.model_fields)
        if unknown:
            raise ValueError(f"unknown settings fields: {sorted(unknown)}")
        async with self._settings_update_lock:
            current = await self.get_settings()
            value = DesktopV2Settings.model_validate({**current.model_dump(), **patch})
            return await self._save_settings_unlocked(value)

    async def _save_settings_unlocked(self, value: DesktopV2Settings) -> DesktopV2Settings:
        self = cast("DesktopV2Service", self)
        _resolved_sandbox_config(value)
        if "observability.provider" in value.component_selections or "observability.provider" in value.component_configs:
            from .observability import normalize_observation_config
            config = normalize_observation_config(
                value.component_selections.get("observability.provider", _DESKTOP_COMPONENT_DEFAULTS["observability.provider"]),
                value.component_configs.get("observability.provider", {}), registry=self.extensions,
            )
            value = value.model_copy(update={"component_configs": {
                **value.component_configs, "observability.provider": config,
            }})
        workspace = await self._ensure_agent_workspace(
            value.agent_workspace_path,
            component_selections=value.component_selections,
            language=value.language,
        )
        normalized = value.model_copy(
            update={
                "agent_workspace_path": str(workspace),
                "projects": [
                    self._normalize_project(project) for project in value.projects
                ],
            }
        )
        async with self._settings_lock:
            writer = asyncio.create_task(asyncio.to_thread(self._write_settings_sync, normalized))
            try:
                await asyncio.shield(writer)
            except asyncio.CancelledError:
                await writer
                raise
        return normalized

    def _write_settings_sync(self, value: DesktopV2Settings) -> None:
        self = cast("DesktopV2Service", self)
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.settings_path)
        self._settings_cache = value
        self._settings_cache_mtime = self.settings_path.stat().st_mtime

    async def add_project(self, name: str, path: str, *, source: Literal["user", "rsi"] = "user") -> DesktopProject:
        self = cast("DesktopV2Service", self)
        root = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("project path must be a directory")
        project = DesktopProject(
            id=f"project_{hashlib.sha256(str(root).encode()).hexdigest()[:20]}",
            name=name.strip() or root.name,
            path=str(root),
            source=source,
        )
        async with self._settings_update_lock:
            settings = await self.get_settings()
            projects = [value for value in settings.projects if value.id != project.id]
            projects.append(project)
            await self._save_settings_unlocked(settings.model_copy(update={"projects": projects}))
        return project

    async def remove_project(self, project_id: str) -> None:
        self = cast("DesktopV2Service", self)
        async with self._settings_update_lock:
            settings = await self.get_settings()
            projects = [value for value in settings.projects if value.id != project_id]
            await self._save_settings_unlocked(settings.model_copy(update={"projects": projects}))

    async def workspace_root(self, workspace_id: str | None, agent_id: str) -> Path:
        self = cast("DesktopV2Service", self)
        if not _AGENT_ID.fullmatch(agent_id):
            raise ValueError("invalid agent id")
        if not workspace_id or workspace_id.startswith("agent:"):
            settings = await self.get_settings()
            return await self._ensure_agent_workspace(
                settings.agent_workspace_path,
                component_selections=settings.component_selections,
                language=settings.language,
            )
        settings = await self.get_settings()
        project = next(
            (value for value in settings.projects if value.id == workspace_id), None
        )
        if project is None:
            raise ValueError("workspace is not registered")
        root = Path(project.path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("workspace is not a directory")
        return root

    def _agent_workspace_path(self, configured: str) -> Path:
        self = cast("DesktopV2Service", self)
        raw = configured.strip()
        target = Path(raw).expanduser() if raw else self.agent_workspace
        if not target.is_absolute():
            raise ValueError("agent workspace path must be absolute or start with ~")
        resolved = target.resolve()
        home = Path.home().resolve()
        filesystem_root = Path(resolved.anchor).resolve()
        if resolved in {home, filesystem_root}:
            raise ValueError("agent workspace path is too broad")
        if resolved.exists() and not resolved.is_dir():
            raise ValueError("agent workspace path must be a directory")
        return resolved

    async def _ensure_agent_workspace(
        self,
        configured: str,
        *,
        component_selections: dict[str, str] | None = None,
        language: str | None = None,
    ) -> Path:
        self = cast("DesktopV2Service", self)
        workspace = self._agent_workspace_path(configured)
        try:
            await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"agent workspace cannot be created: {workspace}") from exc
        if component_selections is None or language is None:
            settings = await self.get_settings()
            if component_selections is None:
                component_selections = settings.component_selections
            if language is None:
                language = settings.language
        plugin_id = component_selections.get(
            "workspace.initializer",
            _DESKTOP_COMPONENT_DEFAULTS["workspace.initializer"],
        )
        plugin_id = _stable_component_id("workspace.initializer", plugin_id)
        initialization_key = (str(workspace), plugin_id, language)
        async with self._workspace_initialization_lock:
            if initialization_key in self._workspace_initializations:
                return workspace
            await self.start()
            assert self.application is not None
            from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
            runtime = self.application.runtime_configuration
            supplied = RuntimeConfig.model_validate(self._host_runtime) if self._host_runtime is not None else None
            selected = (supplied.capabilities.get("workspace.initializer") if supplied is not None else None)
            if selected is None:
                selected = CapabilitySelection(plugin=plugin_id, config={"language": language}
                    if plugin_id == "sage.workspace.initializer.claw" else {})
            if runtime.capabilities.get("workspace.initializer") != selected:
                await self.application.update_runtime(runtime.model_copy(update={"capabilities": {
                    **runtime.capabilities, "workspace.initializer": selected,
                }}))
            await self.application.initialize_workspace(workspace)
            self._workspace_initializations[initialization_key] = workspace
        return workspace

    async def workspace_tree(
        self, workspace_id: str | None, agent_id: str
    ) -> list[dict[str, Any]]:
        self = cast("DesktopV2Service", self)
        root = await self.workspace_root(workspace_id, agent_id)
        settings = await self.get_settings()
        excluded: set[str] = set()
        if workspace_id and not workspace_id.startswith("agent:"):
            agent_workspace = await self._ensure_agent_workspace(
                settings.agent_workspace_path,
                component_selections=settings.component_selections,
                language=settings.language,
            )
            excluded = await asyncio.to_thread(
                self._project_runtime_entries,
                root,
                agent_workspace,
                self.skill_root,
            )
        return await asyncio.to_thread(
            self._tree_sync,
            root,
            settings.max_tree_entries,
            excluded,
        )

    async def read_file(
        self, workspace_id: str | None, agent_id: str, relative_path: str
    ) -> tuple[bytes, str]:
        self = cast("DesktopV2Service", self)
        root = await self.workspace_root(workspace_id, agent_id)
        path = self._resolve_child(root, relative_path)
        settings = await self.get_settings()
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        if path.stat().st_size > settings.max_preview_bytes:
            raise ValueError("file exceeds preview size limit")
        return await asyncio.to_thread(path.read_bytes), self._mime(path)

    async def upload(
        self,
        workspace_id: str | None,
        agent_id: str,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        self = cast("DesktopV2Service", self)
        root = await self.workspace_root(workspace_id, agent_id)
        settings = await self.get_settings()
        _, sandbox_config = _resolved_sandbox_config(settings)
        workspace_root = _sandbox_workspace_root(sandbox_config, root)
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("invalid filename")
        uploads = root / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        stored_name = await asyncio.to_thread(
            self._store_upload,
            uploads,
            safe_name,
            content,
        )
        return {
            "name": stored_name,
            "path": f"uploads/{stored_name}",
            "virtual_path": workspace_root.rstrip("/")
            + f"/uploads/{stored_name}",
            "size": len(content),
        }

    async def _initialize_user(self, user_id: str) -> None:
        self = cast("DesktopV2Service", self)
        initialize = getattr(self.catalog, "initialize_user", None)
        if initialize is not None:
            await initialize(user_id)

    def _skill_provider(self, agent=None) -> FilesystemSkillProvider:
        self = cast("DesktopV2Service", self)
        module_path = Path(__file__).resolve()
        source_skills = module_path.parents[3] / "skills"
        bundled_skills = module_path.parents[4] / "skills"
        builtin_skills = source_skills if source_skills.is_dir() else bundled_skills
        roots = (self.skill_root, builtin_skills)
        if agent is not None and agent.config.get("rsiPackage"):
            from sagents.v2.agent.management import AgentPackageBundle
            bundle = AgentPackageBundle.model_validate(agent.config["rsiPackage"])
            # Content-addressed, per-agent overlay. Never overwrite shared Skills.
            import hashlib
            import json
            asset_identity = hashlib.sha256(json.dumps(agent.config.get("rsiAssets") or {}, sort_keys=True).encode()).hexdigest()
            overlay = self.runtime_root / "agent-packages" / f"{bundle.content_hash}-{asset_identity}"
            for name, content in bundle.files.items():
                target = overlay / name
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
            import base64
            assets = agent.config.get("rsiAssets") or {}
            # Reuse package path validation before materializing binary resources.
            AgentPackageBundle(manifest=bundle.manifest, files=assets)
            for name, content in assets.items():
                target = overlay / name
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(base64.b64decode(content, validate=True))
            roots = (overlay / "skills", *roots)
        return FilesystemSkillProvider(roots)

    def _imported_skill_root(self, skill_name: str) -> Path | None:
        self = cast("DesktopV2Service", self)
        if not _SKILL_NAME.fullmatch(skill_name):
            return None
        root = self.skill_root.resolve()
        unresolved = root / skill_name
        if unresolved.is_symlink():
            return None
        target = unresolved.resolve()
        if (
            target.parent != root
            or not target.is_dir()
            or not (target / "SKILL.md").is_file()
        ):
            return None
        return target

    def _skill_summary(
        self,
        skill_name: str,
        descriptor: SkillDescriptor,
    ) -> dict[str, Any]:
        self = cast("DesktopV2Service", self)
        return {
            **descriptor.model_dump(mode="json"),
            "can_delete": self._imported_skill_root(skill_name) is not None,
        }

    @staticmethod
    def _skill_name(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^name:\s*['\"]?([^'\"\n]+)", text)
        name = match.group(1).strip() if match else path.parent.name
        if not _SKILL_NAME.fullmatch(name) or name in {".", ".."}:
            raise ValueError("SKILL.md must define a valid name")
        return name

    @staticmethod
    def _context(user_id: str, *, language: str = "en") -> RequestContext:
        return RequestContext(
            actor=ActorRef(
                principal_id=user_id,
                # The fixed local Desktop principal predates tenant scoping.
                # Keep its durable identity aligned with owner adoption and
                # existing Sessions; explicit hosted/test users stay scoped.
                tenant_id=None if user_id == "default_user" else user_id,
                principal_type=PrincipalType.USER,
                scopes=(
                    "tool.read",
                    "tool.write",
                    "tool.internal",
                    "tool.external_side_effect",
                    "skill.load",
                    "workspace.read",
                    "workspace.write",
                    "workspace.delete",
                    "process.run",
                ),
            ),
            language=language,
        )

    async def _run_context(self, run_id: str, user_id: str) -> RequestContext:
        self = cast("DesktopV2Service", self)
        await self.start()
        assert self.session_access is not None
        context = self._context(user_id)
        command = await self.session_access.get_start_command(run_id, context)
        return self._context(
            user_id,
            language=str(command.config.metadata.get("response_language") or "en"),
        )

    @staticmethod
    def _normalize_project(project: DesktopProject) -> DesktopProject:
        root = Path(project.path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"project path is not a directory: {project.path}")
        return project.model_copy(
            update={"path": str(root), "name": project.name.strip() or root.name}
        )

    @staticmethod
    def _resolve_child(root: Path, relative_path: str) -> Path:
        raw = relative_path.replace("\\", "/").lstrip("/")
        candidate = (root / raw).resolve()
        if root != candidate and root not in candidate.parents:
            raise PermissionError("path is outside the active workspace")
        return candidate

    @classmethod
    def _store_upload(
        cls,
        uploads: Path,
        safe_name: str,
        content: bytes,
    ) -> str:
        source = Path(safe_name)
        index = 0
        while True:
            candidate_name = (
                safe_name
                if index == 0
                else f"{source.stem}_{index}{source.suffix}"
            )
            target = cls._resolve_child(uploads, candidate_name)
            if target.exists():
                if target.is_file() and target.read_bytes() == content:
                    return candidate_name
                index += 1
                continue
            try:
                with target.open("xb") as output:
                    output.write(content)
                return candidate_name
            except FileExistsError:
                # Another upload claimed this name after the existence check.
                continue

    @classmethod
    def _project_runtime_entries(
        cls,
        project_root: Path,
        agent_workspace: Path,
        source_skills: Path,
    ) -> set[str]:
        excluded: set[str] = (
            {".sandbox"} if (project_root / ".sandbox").is_dir() else set()
        )
        for name in {"AGENT.md", "IDENTITY.md", "MEMORY.md", "SOUL.md", "USER.md"}:
            project_file = project_root / name
            agent_file = agent_workspace / name
            if cls._same_runtime_entry(project_file, agent_file):
                excluded.add(name)

        for name in {"data", "logs", "memory", "projects", "temp"}:
            candidate = project_root / name
            if candidate.is_dir() and not any(candidate.iterdir()):
                excluded.add(name)

        project_skills = project_root / "skills"
        if project_skills.is_dir() and source_skills.is_dir():
            children = [
                value for value in project_skills.iterdir() if not value.is_symlink()
            ]
            copied = {
                value.name
                for value in children
                if cls._same_runtime_entry(value, source_skills / value.name)
            }
            if children and len(copied) == len(children):
                excluded.add("skills")
            else:
                excluded.update(f"skills/{name}" for name in copied)
        return excluded

    @classmethod
    def _same_runtime_entry(cls, left: Path, right: Path) -> bool:
        if left.is_file() and right.is_file():
            return left.read_bytes() == right.read_bytes()
        if not left.is_dir() or not right.is_dir():
            return False
        left_entries = {
            value.relative_to(left).as_posix(): value
            for value in left.rglob("*")
            if not value.is_symlink()
        }
        right_entries = {
            value.relative_to(right).as_posix(): value
            for value in right.rglob("*")
            if not value.is_symlink()
        }
        if left_entries.keys() != right_entries.keys():
            return False
        return all(
            left_value.is_dir() == right_entries[relative].is_dir()
            and (
                left_value.is_dir()
                or left_value.read_bytes() == right_entries[relative].read_bytes()
            )
            for relative, left_value in left_entries.items()
        )

    def _tree_sync(
        self,
        root: Path,
        maximum: int,
        excluded: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        count = 0
        excluded = excluded or set()

        def visit(directory: Path) -> list[dict[str, Any]]:
            nonlocal count
            values = []
            try:
                children = sorted(
                    directory.iterdir(),
                    key=lambda value: (value.is_file(), value.name.lower()),
                )
            except PermissionError:
                return values
            for child in children:
                if count >= maximum:
                    break
                if child.is_symlink():
                    continue
                if child.name in {".git", "node_modules", "__pycache__", ".venv"}:
                    continue
                relative = child.relative_to(root).as_posix()
                if relative in excluded:
                    continue
                count += 1
                is_directory = child.is_dir()
                values.append(
                    {
                        "name": child.name,
                        "path": relative,
                        "is_directory": is_directory,
                        "size": 0 if is_directory else child.stat().st_size,
                        "children": visit(child) if is_directory else [],
                    }
                )
            return values

        return visit(root)

    @staticmethod
    def _mime(path: Path) -> str:
        if path.suffix.lower() in _TEXT_EXTENSIONS:
            return "text/plain; charset=utf-8"
        import mimetypes

        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
