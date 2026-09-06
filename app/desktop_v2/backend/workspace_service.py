from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
from pathlib import Path
from typing import Any


from app.desktop_v2.backend.package import (
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
from app.desktop_v2.backend.package import desktop_v2_manifest
from app.desktop_v2.backend.schemas import (
    AgentCreate as AgentCreate,
    AgentSettingsPatch as AgentSettingsPatch,
    ComponentSelectionRequest as ComponentSelectionRequest,
    DesktopProject,
    DesktopRunRequest as DesktopRunRequest,
    DesktopV2Settings,
    ModelProviderCreate as ModelProviderCreate,
    ModelProviderPatch as ModelProviderPatch,
)
from app.desktop_v2.backend.run_lifecycle import (
    DesktopRunResources as _DesktopRunResources,  # noqa: F401 - compatibility export
)
from app.desktop_v2.backend.run_context import (
    AgentRosterContextProvider as AgentRosterContextProvider,
)
from app.desktop_v2.backend.runtime_config import (
    _AGENT_ID,
    _SKILL_NAME,
    _resolved_sandbox_config,
    _sandbox_workspace_root,
)
from app.desktop_v2.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)

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

    async def get_settings(self) -> DesktopV2Settings:
        async with self._settings_lock:
            if not self.settings_path.exists():
                value = DesktopV2Settings()
            else:
                value = DesktopV2Settings.model_validate_json(
                    self.settings_path.read_text(encoding="utf-8")
                )
        return value.model_copy(
            update={
                "agent_workspace_path": str(
                    self._agent_workspace_path(value.agent_workspace_path)
                )
            }
        )

    def _read_settings_sync(self) -> DesktopV2Settings:
        if not self.settings_path.exists():
            self._settings_cache = DesktopV2Settings()
            self._settings_cache_mtime = None
            return self._settings_cache
        mtime = self.settings_path.stat().st_mtime
        cached = getattr(self, "_settings_cache", None)
        if cached is not None and getattr(self, "_settings_cache_mtime", None) == mtime:
            return cached
        settings = DesktopV2Settings.model_validate_json(
            self.settings_path.read_text(encoding="utf-8")
        )
        self._settings_cache = settings
        self._settings_cache_mtime = mtime
        return settings

    async def save_settings(self, value: DesktopV2Settings) -> DesktopV2Settings:
        _resolved_sandbox_config(value)
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
            await asyncio.to_thread(self._write_settings_sync, normalized)
        return normalized

    def _write_settings_sync(self, value: DesktopV2Settings) -> None:
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.settings_path)
        self._settings_cache = value
        self._settings_cache_mtime = self.settings_path.stat().st_mtime

    async def add_project(self, name: str, path: str) -> DesktopProject:
        root = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("project path must be a directory")
        project = DesktopProject(
            id=f"project_{hashlib.sha256(str(root).encode()).hexdigest()[:20]}",
            name=name.strip() or root.name,
            path=str(root),
        )
        settings = await self.get_settings()
        projects = [value for value in settings.projects if value.id != project.id]
        projects.append(project)
        await self.save_settings(settings.model_copy(update={"projects": projects}))
        return project

    async def remove_project(self, project_id: str) -> None:
        settings = await self.get_settings()
        projects = [value for value in settings.projects if value.id != project_id]
        await self.save_settings(settings.model_copy(update={"projects": projects}))

    async def workspace_root(self, workspace_id: str | None, agent_id: str) -> Path:
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
            settings = await self.get_settings()
            ports = await self.application.materialize_agent(
                desktop_v2_manifest(
                    session_root=self.runtime_root,
                    component_selections=component_selections,
                    component_configs=settings.component_configs,
                    language=language,
                ),
                locked_configs={"workspace.initializer": {"language": language}},
                cache_identities={
                    "workspace.initializer": {
                        "plugin": plugin_id,
                        "language": language,
                    }
                },
            )
            initialization_error: BaseException | None = None
            try:
                initializer = ports.workspace_initializer
                initialize = initializer.initialize
                if inspect.iscoroutinefunction(initialize):
                    result = initialize(workspace)
                else:
                    result = await asyncio.to_thread(initialize, workspace)
                if inspect.isawaitable(result):
                    await result
            except BaseException as exc:
                initialization_error = exc
            cleanup_errors: list[BaseException] = []
            for handle in reversed(ports.scope_handles):
                try:
                    await handle.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if initialization_error is not None:
                if cleanup_errors:
                    raise initialization_error from cleanup_errors[0]
                raise initialization_error
            if cleanup_errors:
                raise cleanup_errors[0]
            self._workspace_initializations[initialization_key] = workspace
        return workspace

    async def workspace_tree(
        self, workspace_id: str | None, agent_id: str
    ) -> list[dict[str, Any]]:
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
        initialize = getattr(self.catalog, "initialize_user", None)
        if initialize is not None:
            await initialize(user_id)

    def _skill_provider(self) -> FilesystemSkillProvider:
        module_path = Path(__file__).resolve()
        source_skills = module_path.parents[2] / "skills"
        bundled_skills = module_path.parents[3] / "skills"
        builtin_skills = source_skills if source_skills.is_dir() else bundled_skills
        return FilesystemSkillProvider((self.skill_root, builtin_skills))

    def _imported_skill_root(self, skill_name: str) -> Path | None:
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
        await self.start()
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
