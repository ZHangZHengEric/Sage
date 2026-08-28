from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from app.desktop_v2.backend.catalog import (
    DesktopAgentRecord,
    DesktopCatalogStore,
    DesktopMcpRecord,
    DesktopModelProviderRecord,
    JsonDesktopCatalogStore,
)
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from app.desktop_v2.backend.legacy_import import read_legacy_desktop_settings
from app.desktop_v2.backend.session_index import JsonDesktopSessionIndex
from sagents.v2 import SAgent
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
    OfficialToolRuntime,
    official_tool_definitions,
)
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import EventCursor, SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionMergeStrategy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.builder import AgentRuntimeFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.package.manifest.agents import (
    AgentBudgets,
    AgentDefinition,
    ApplicationEntrypoint,
    Instructions,
)
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.models import (
    ModelCapabilityDeclaration,
    ModelLimits,
    ModelRequestDefaults,
    ModelRoute,
)
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.root import ManifestMetadata, SageManifest
from sagents.v2.package.manifest.runtime import PolicyConfig
from sagents.v2.runtime.session import (
    FilesystemSessionStore,
)
from sagents.v2.context import (
    ContextSegment,
    ContextStability,
    ModelConversationSummarizer,
    SessionDerivedConversationSummaryStore,
    TokenEstimatorRegistry,
)
from sagents.v2.runtime.credentials import CredentialMaterial
from sagents.v2.model import (
    RecordingModelProvider,
    model_protocol_descriptor,
    resolve_model_protocol,
)
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.agent.policy import (
    ApprovalStrategy,
    DefaultToolPolicy,
)
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)
from sagents.v2.skill import (
    FilesystemSkillProvider,
    SessionDerivedSkillActivationRepository,
    SkillLoadTool,
)
from sagents.v2.tool import decorated_tool_definition
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.runtime.observability import FilesystemDiagnosticSink
from sagents.v2.skill.contracts import SkillBundle
from sagents.v2.tool import (
    CompositeToolCatalog,
    CompositeToolExecutor,
    McpServerConfig,
    McpToolPlugin,
    ToolDefinition,
)


_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
LOGGER = logging.getLogger(__name__)
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,191}$")
_SKILL_NAME = re.compile(r"^[^\\/\x00]{1,192}$")
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


def _mcp_source(tool_name: str) -> str:
    del tool_name
    return "MCP Server"


class DesktopProject(BaseModel):
    id: str
    name: str
    path: str


class DesktopV2Settings(BaseModel):
    theme_mode: Literal["system", "light", "dark"] = "system"
    language: Literal[
        "system", "zh", "en", "pt", "es", "fr", "de", "ja", "ko", "ru"
    ] = "system"
    default_agent_id: str | None = None
    projects: list[DesktopProject] = Field(default_factory=list)
    agent_workspace_path: str = ""
    max_preview_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    max_tree_entries: int = Field(default=6_000, ge=100, le=50_000)
    component_selections: dict[str, str] = Field(default_factory=dict)


class ComponentSelectionRequest(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=192)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentSettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    system_prefix: str | None = Field(default=None, max_length=20_000)
    system_context: dict[str, Any] | None = None
    llm_provider_id: str | None = None
    fast_llm_provider_id: str | None = None
    agent_mode: Literal["simple", "fibre", "team"] | None = None
    max_loop_count: int | None = Field(default=None, ge=1, le=10_000)
    deep_thinking: bool | None = None
    thinking_level: (
        Literal["minimal", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    available_tools: list[str] | None = None
    available_skills: list[str] | None = None

    model_config = {"extra": "forbid"}


class MCPConnectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    protocol: Literal["stdio", "sse", "streamable_http"]
    streamable_http_url: str | None = None
    sse_url: str | None = None
    api_key: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class ModelProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    protocol: (
        Literal["openai-chat-completions", "openai-responses", "anthropic-messages"]
        | None
    ) = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2_000)
    api_keys: list[str] | None = None
    supports_multimodal: bool | None = None
    supports_structured_output: bool | None = None
    is_default: bool | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    max_model_len: int | None = Field(default=None, gt=0)
    model_config = {"extra": "forbid"}


class ModelProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    protocol: Literal[
        "openai-chat-completions", "openai-responses", "anthropic-messages"
    ] = "openai-responses"
    model: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=2_000)
    api_keys: list[str] = Field(default_factory=list)
    supports_multimodal: bool = True
    supports_structured_output: bool = True
    is_default: bool = False
    max_tokens: int = Field(default=8192, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    max_model_len: int = Field(default=128_000, gt=0)
    model_config = {"extra": "forbid"}


class RunMessage(BaseModel):
    role: Literal["user", "assistant", "system", "developer"]
    text: str


class DesktopRunRequest(BaseModel):
    agent_id: str
    messages: list[RunMessage]
    session_id: str | None = None
    workspace_id: str | None = None
    preferred_skills: list[str] = Field(default_factory=list)
    attachment_paths: list[str] = Field(default_factory=list)
    approval_mode: Literal["always_ask", "high_risk", "auto_approve"] = "high_risk"
    idempotency_key: str | None = None
    session_concurrency_mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL
    base_session_revision: int | None = Field(default=None, ge=0)


class LocalSkillWorkspace:
    """Materialize exactly one Skill after an explicit load_skill call."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = asyncio.Lock()

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        del run_id
        relative = destination.removeprefix("/workspace/").lstrip("/")
        target = (self.root / relative).resolve()
        if self.root != target and self.root not in target.parents:
            raise PermissionError("skill destination is outside the active workspace")
        async with self._lock:
            await asyncio.to_thread(self._materialize_sync, bundle, target)
        return f"/workspace/{relative}"

    def _materialize_sync(self, bundle: SkillBundle, target: Path) -> None:
        if target.exists():
            if (
                not target.is_dir()
                or self._hash_directory(target) != bundle.content_hash
            ):
                from sagents.v2.contracts.errors import (
                    ErrorCategory,
                    RuntimeErrorInfo,
                    SageV2Error,
                )

                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="skill.workspace_conflict",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            f"workspace skill {target.name!r} already exists with "
                            "different content; it was not overwritten"
                        ),
                        safe_to_resume=True,
                    )
                )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.sage-load-", dir=target.parent)
        )
        try:
            for relative, content in bundle.files.items():
                candidate = temporary / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_bytes(content)
            temporary.replace(target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _hash_directory(root: Path) -> str:
        digest = hashlib.sha256()
        for candidate in sorted(root.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(candidate.read_bytes())
            digest.update(b"\0")
        return f"sha256:{digest.hexdigest()}"


class PreferredSkillsContextProvider:
    """Project selected Skills into context without fetching or copying them."""

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        del run_id
        selected = command.config.metadata.get("preferred_skills") or []
        if not selected:
            return ()
        return (
            ContextSegment(
                segment_id="desktop_preferred_skills",
                content=(
                    "The user marked these Skills as relevant: "
                    + ", ".join(selected)
                    + ". They are not loaded. Call load_skill before using one."
                ),
                stability=ContextStability.SEMI_STABLE,
                priority=-45,
            ),
        )


class _DesktopDriver:
    def __init__(
        self,
        service: "DesktopV2Service",
        loop,
        workspace: Path,
        sandbox_handle,
    ) -> None:
        self.service = service
        self.loop = loop
        self.workspace = workspace
        self.sandbox_handle = sandbox_handle

    async def execute(self, run_id: str, context: RequestContext):
        return await self.loop.execute(run_id, context)

    async def resume(self, run_id: str, context: RequestContext):
        return await self.loop.resume(run_id, context)


class DesktopV2Service:
    def __init__(
        self,
        root: Path | None = None,
        *,
        catalog: DesktopCatalogStore | None = None,
        legacy_db_path: Path | None = None,
    ) -> None:
        configured_root = os.getenv("SAGE_DESKTOP_V2_DATA_DIR")
        use_default_root = root is None and (
            not configured_root
            or Path(configured_root).expanduser().resolve()
            == (Path.home() / "sage").resolve()
        )
        self.root = (
            root
            or (Path(configured_root).expanduser() if configured_root else None)
            or Path.home() / "sage"
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.agent_workspace = self.root / "agent_workspace"
        self.runtime_root = self.root / "runtime"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.runtime_root / "settings.json"
        self._read_settings_sync()
        self.session_store = FilesystemSessionStore(self.runtime_root / "session-store")
        self.runtime = HarnessRuntime(self.session_store)
        self.summary_store = SessionDerivedConversationSummaryStore(self.session_store)
        self.activations = SessionDerivedSkillActivationRepository(
            self.session_store,
            self._session_id_for_run,
        )
        self.diagnostics = FilesystemDiagnosticSink(self.runtime_root / "diagnostics")
        self.session_index = JsonDesktopSessionIndex(
            self.runtime_root / "session-index.json"
        )
        self.catalog = catalog or JsonDesktopCatalogStore(
            self.runtime_root / "desktop-catalog.json"
        )
        self.legacy_db_path = (
            legacy_db_path
            if legacy_db_path is not None
            else Path.home() / ".sage" / "sage.db"
            if use_default_root
            else None
        )
        self.skill_root = self.root / "skills"
        self.skill_root.mkdir(parents=True, exist_ok=True)
        self._settings_lock = asyncio.Lock()
        self._legacy_import_lock = asyncio.Lock()
        self._legacy_imported_users: set[str] = set()
        self._drivers: dict[str, _DesktopDriver] = {}
        self.extensions = builtin_extension_registry()

    async def initialize_agent_workspace(self) -> Path:
        settings = await self.get_settings()
        return await self._ensure_agent_workspace(settings.agent_workspace_path)

    async def list_sessions(self) -> list[dict[str, Any]]:
        values = await self.session_index.list()
        return [value.model_dump(mode="json") for value in values]

    async def delete_session(self, session_id: str) -> None:
        await self.session_store.delete_session(session_id)
        try:
            await self.session_index.remove(session_id)
        except Exception:
            LOGGER.exception("Desktop Session index removal failed for %s", session_id)

    async def session_snapshot(self, session_id: str) -> dict[str, Any]:
        session = await self.session_store.get_session(session_id)
        runs = await self.session_store.list_session_runs(session_id)
        proposals = await self.session_store.list_session_commit_proposals(session_id)
        return {
            "session": session.model_dump(mode="json"),
            "runs": [value.model_dump(mode="json") for value in runs],
            "commit_proposals": [value.model_dump(mode="json") for value in proposals],
            "diagnostics": {
                "format_version": self.diagnostics.format_version,
                "path": str(self.diagnostics.root),
                "authoritative": False,
            },
        }

    async def session_runs(self, session_id: str) -> list[dict[str, Any]]:
        values = await self.session_store.list_session_runs(session_id)
        return [value.model_dump(mode="json") for value in values]

    async def session_commit_proposals(self, session_id: str) -> list[dict[str, Any]]:
        values = await self.session_store.list_session_commit_proposals(session_id)
        return [value.model_dump(mode="json") for value in values]

    async def propose_session_commit(self, run_id: str, user_id: str):
        run = await self.session_store.get_run(run_id)
        result = await self.runtime.propose_session_commit(
            ProposeSessionCommit(
                run_id=run_id,
                expected_run_revision=run.revision,
                idempotency_key=new_id("session_commit_propose"),
            ),
            self._context(user_id),
        )
        await self._index_session(run.session_id)
        return result

    async def publish_session_commit(
        self,
        proposal_id: str,
        merge_strategy: SessionMergeStrategy,
        user_id: str,
    ):
        proposal = await self.session_store.get_session_commit_proposal(proposal_id)
        session = await self.session_store.get_session(proposal.session_id)
        result = await self.runtime.publish_session_commit(
            PublishSessionCommit(
                proposal_id=proposal_id,
                expected_proposal_revision=proposal.revision,
                expected_session_revision=session.revision,
                merge_strategy=merge_strategy,
                idempotency_key=new_id("session_commit_publish"),
            ),
            self._context(user_id),
        )
        await self._index_session(proposal.session_id)
        return result

    async def reject_session_commit(self, proposal_id: str, reason: str, user_id: str):
        proposal = await self.session_store.get_session_commit_proposal(proposal_id)
        session = await self.session_store.get_session(proposal.session_id)
        result = await self.runtime.reject_session_commit(
            RejectSessionCommit(
                proposal_id=proposal_id,
                expected_proposal_revision=proposal.revision,
                expected_session_revision=session.revision,
                reason=reason,
                idempotency_key=new_id("session_commit_reject"),
            ),
            self._context(user_id),
        )
        await self._index_session(proposal.session_id)
        return result

    async def session_events(
        self, session_id: str, after_sequence: int = 0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        values = await self.session_store.read_session_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        return [value.model_dump(mode="json") for value in values]

    async def list_llm_requests(
        self, session_id: str, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        await self.session_store.get_session(session_id)
        if run_id is not None:
            run = await self.session_store.get_run(run_id)
            if run.session_id != session_id:
                raise ValueError(f"run {run_id} does not belong to {session_id}")
        return list(
            await self.diagnostics.list_model_requests(
                session_id=session_id,
                run_id=run_id,
            )
        )

    async def get_llm_request(
        self, session_id: str, run_id: str, request_id: str
    ) -> dict[str, Any]:
        run = await self.session_store.get_run(run_id)
        if run.session_id != session_id:
            raise ValueError(f"run {run_id} does not belong to {session_id}")
        return await self.diagnostics.get_model_request(
            session_id=session_id,
            run_id=run_id,
            request_id=request_id,
        )

    async def list_agents(self, user_id: str) -> list[dict[str, Any]]:
        await self._initialize_user(user_id)
        values = await self.catalog.list_agents(user_id)
        return [
            {
                "id": value.agent_id,
                "name": value.name,
                "is_default": value.is_default,
                "tool_count": len(value.config.get("availableTools") or []),
                "skill_count": len(value.config.get("availableSkills") or []),
            }
            for value in values
        ]

    async def list_skills(self, agent_id: str, user_id: str) -> list[dict[str, Any]]:
        agent = await self._agent(agent_id, user_id)
        allowed = set(agent.config.get("availableSkills") or [])
        values = self._skill_provider().descriptors()
        names = sorted(allowed if allowed else values)
        return [
            values[name].model_dump(mode="json")
            for name in names
            if name in values and _SKILL_NAME.fullmatch(name)
        ]

    async def list_skill_catalog(self, user_id: str) -> list[dict[str, Any]]:
        del user_id
        values = self._skill_provider().descriptors()
        return [
            values[name].model_dump(mode="json")
            for name in sorted(values)
            if _SKILL_NAME.fullmatch(name)
        ]

    async def get_skill_content(self, skill_name: str, user_id: str) -> str:
        del user_id
        if not _SKILL_NAME.fullmatch(skill_name):
            raise ValueError("invalid skill name")
        try:
            root = self._skill_provider()._skill_root(skill_name)
        except SageV2Error as exc:
            raise ValueError(f"Skill not found: {skill_name}") from exc

        skill_file = (root / "SKILL.md").resolve()
        if root not in skill_file.parents or not skill_file.is_file():
            raise ValueError("Skill folder does not contain SKILL.md")
        try:
            return await asyncio.to_thread(skill_file.read_text, encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SKILL.md must be UTF-8 encoded") from exc

    async def import_skill_folder(
        self,
        folder_path: str,
        user_id: str,
    ) -> dict[str, Any]:
        normalized = Path(folder_path).expanduser().resolve()
        if not normalized.is_dir():
            raise ValueError("Skill folder does not exist")
        if not (normalized / "SKILL.md").is_file():
            raise ValueError("Skill folder must contain SKILL.md")
        skill_name = self._skill_name(normalized / "SKILL.md")
        if not skill_name:
            raise ValueError("SKILL.md must define a valid name")
        target = (self.skill_root / skill_name).resolve()
        if target.parent != self.skill_root.resolve():
            raise ValueError("invalid Skill name")
        if target.exists():
            raise ValueError(f"Skill already exists: {skill_name}")
        await asyncio.to_thread(shutil.copytree, normalized, target)
        return {"success_count": 1, "imported_names": [skill_name]}

    async def list_tools(self, user_id: str) -> list[dict[str, Any]]:
        definitions = [
            {
                **value.model_dump(mode="json"),
                "type": "basic",
                "source": "基础工具",
            }
            for value in self._native_tool_definitions()
        ]
        mcp = await self._mcp_plugin(user_id)
        definitions.extend(
            {
                **value.model_dump(mode="json"),
                "type": "mcp",
                "source": _mcp_source(value.name),
            }
            for value in await mcp.list_tools(run_id="desktop-tool-catalog")
        )
        return definitions

    def _official_tools(self, runtime: OfficialToolRuntime) -> OfficialToolPlugin:
        return OfficialToolPlugin(
            ExtensionScopeContext(
                scope=ExtensionScope.AGENT,
                scope_id="desktop-v2-official-tools",
                config={"runtime": runtime},
            )
        )

    def _native_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        definitions = official_tool_definitions()
        load_skill = decorated_tool_definition(SkillLoadTool.execute)
        return (*definitions, *((load_skill,) if load_skill is not None else ()))

    async def _mcp_plugin(self, user_id: str) -> McpToolPlugin:
        await self._initialize_user(user_id)
        values = await self.catalog.list_mcp(user_id)
        return McpToolPlugin(
            tuple(self._mcp_config(value) for value in values if not value.disabled)
        )

    @staticmethod
    def _mcp_config(value: DesktopMcpRecord) -> McpServerConfig:
        streamable_url = value.streamable_http_url
        if value.kind == "anytool":
            port = os.getenv("SAGE_DESKTOP_V2_PORT") or os.getenv("SAGE_PORT") or "8080"
            streamable_url = f"http://127.0.0.1:{port}/api/mcp/anytool/{value.name}"
        return McpServerConfig(
            name=value.name,
            protocol=value.protocol,
            url=(
                streamable_url if value.protocol == "streamable_http" else value.sse_url
            ),
            api_key=value.api_key,
            command=value.command,
            args=value.args,
            env=value.env,
        )

    async def list_model_providers(self, user_id: str) -> list[dict[str, Any]]:
        await self._initialize_user(user_id)
        values = await self.catalog.list_model_providers(user_id)
        return [
            {
                "id": value.id,
                "name": value.name,
                "protocol": value.protocol,
                "model": value.model,
                "base_url": value.base_url,
                "api_key_configured": bool(value.api_key),
                "supports_multimodal": value.supports_multimodal,
                "supports_structured_output": bool(value.supports_structured_output),
                "is_default": value.is_default,
                "max_tokens": value.max_tokens,
                "temperature": value.temperature,
                "top_p": value.top_p,
                "max_model_len": value.max_model_len,
            }
            for value in values
        ]

    async def reveal_model_provider_api_key(
        self, provider_id: str, user_id: str
    ) -> dict[str, str]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("model provider is not configured for this Desktop user")
        if not provider.api_key:
            raise ValueError("model provider has no API key")
        return {"api_key": provider.api_key}

    async def delete_model_provider(
        self, provider_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("Provider not found")
        if provider.is_default:
            values = await self.catalog.list_model_providers(provider.user_id)
            replacement = next(
                (value for value in values if value.id != provider_id), None
            )
            if replacement is None:
                raise ValueError("Cannot delete the only model provider")
            replacement.is_default = True
            await self.catalog.save_model_provider(
                replacement.model_copy(update={"is_default": True})
            )
        await self.catalog.delete_model_provider(provider_id, user_id)
        return await self.list_model_providers(user_id)

    async def create_model_provider(
        self, request: ModelProviderCreate, user_id: str
    ) -> dict[str, Any]:
        await self._initialize_user(user_id)
        keys = [value.strip() for value in request.api_keys if value.strip()]
        if len(keys) > 1:
            raise ValueError("Desktop model providers accept one API key")
        existing = await self.catalog.list_model_providers(user_id)
        make_default = request.is_default or not existing
        if make_default:
            for value in existing:
                if value.is_default:
                    await self.catalog.save_model_provider(
                        value.model_copy(update={"is_default": False})
                    )
        candidate = DesktopModelProviderRecord(
            id=new_id("model"),
            user_id=user_id,
            name=request.name.strip(),
            protocol=request.protocol,
            model=request.model.strip(),
            base_url=request.base_url.strip(),
            api_key=keys[0] if keys else "",
            supports_multimodal=request.supports_multimodal,
            supports_structured_output=request.supports_structured_output,
            is_default=make_default,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            max_model_len=request.max_model_len,
        )
        self._validate_model_route(candidate)
        await self.catalog.save_model_provider(candidate)
        values = await self.list_model_providers(user_id)
        return next(value for value in values if value["id"] == candidate.id)

    async def patch_model_provider(
        self, provider_id: str, patch: ModelProviderPatch, user_id: str
    ) -> dict[str, Any]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("Provider not found")
        updates = patch.model_dump(exclude_unset=True, exclude={"api_keys"})
        if patch.api_keys is not None:
            keys = [value.strip() for value in patch.api_keys if value.strip()]
            if len(keys) > 1:
                raise ValueError("Desktop model providers accept one API key")
            updates["api_key"] = keys[0] if keys else ""
        updates["updated_at"] = utc_now()
        candidate = provider.model_copy(update=updates)
        self._validate_model_route(candidate)
        if candidate.is_default and not provider.is_default:
            for value in await self.catalog.list_model_providers(user_id):
                if value.id != provider_id and value.is_default:
                    await self.catalog.save_model_provider(
                        value.model_copy(update={"is_default": False})
                    )
        await self.catalog.save_model_provider(candidate)
        values = await self.list_model_providers(user_id)
        return next(value for value in values if value["id"] == provider_id)

    @staticmethod
    def _validate_model_route(provider: DesktopModelProviderRecord) -> None:
        """Validate a saved route without making a network request."""

        if provider.max_tokens > provider.max_model_len:
            raise ValueError("max_tokens cannot exceed max_model_len")
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=provider.max_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=provider.max_tokens,
            ),
        )
        model_protocol_descriptor(route.provider)

    async def get_agent_settings(self, agent_id: str, user_id: str) -> dict[str, Any]:
        agent = await self._agent(agent_id, user_id)
        config = dict(agent.config or {})
        deep_thinking, thinking_level = self._thinking_config(agent)
        return {
            "id": agent.agent_id,
            "name": agent.name,
            "description": config.get("description") or "",
            "system_prefix": config.get("systemPrefix")
            or config.get("system_prefix")
            or "",
            "system_context": config.get("systemContext")
            or config.get("system_context")
            or {},
            "llm_provider_id": config.get("llm_provider_id"),
            "fast_llm_provider_id": config.get("fast_llm_provider_id"),
            "agent_mode": config.get("agentMode")
            or config.get("agent_mode")
            or "simple",
            "max_loop_count": int(
                config.get("maxLoopCount") or config.get("max_loop_count") or 100
            ),
            "deep_thinking": deep_thinking,
            "thinking_level": thinking_level,
            "available_tools": list(config.get("availableTools") or []),
            "available_skills": list(config.get("availableSkills") or []),
            "is_default": agent.is_default,
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
        }

    async def patch_agent_settings(
        self,
        agent_id: str,
        patch: AgentSettingsPatch,
        user_id: str,
    ) -> dict[str, Any]:
        agent = await self._agent(agent_id, user_id)
        config = dict(agent.config or {})
        fields = patch.model_fields_set
        if "name" in fields:
            agent.name = str(patch.name or "").strip()
            if not agent.name:
                raise ValueError("agent name cannot be empty")
            config["name"] = agent.name
        mapping = {
            "description": "description",
            "system_prefix": "systemPrefix",
            "system_context": "systemContext",
            "llm_provider_id": "llm_provider_id",
            "fast_llm_provider_id": "fast_llm_provider_id",
            "agent_mode": "agentMode",
            "max_loop_count": "maxLoopCount",
            "deep_thinking": "deepThinking",
            "thinking_level": "thinkingLevel",
            "available_tools": "availableTools",
            "available_skills": "availableSkills",
        }
        for field, target in mapping.items():
            if field in fields:
                config[target] = getattr(patch, field)
        if "available_tools" in fields:
            known = {value["name"] for value in await self.list_tools(user_id)}
            unknown = set(patch.available_tools or []) - known
            if unknown:
                raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
        if "available_skills" in fields:
            known = {value["name"] for value in await self.list_skill_catalog(user_id)}
            unknown = set(patch.available_skills or []) - known
            if unknown:
                raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
        agent.config = config
        await self.catalog.save_agent(
            agent.model_copy(update={"config": config, "updated_at": utc_now()})
        )
        return await self.get_agent_settings(agent_id, user_id)

    async def delete_agent(self, agent_id: str, user_id: str) -> list[dict[str, Any]]:
        agent = await self._agent(agent_id, user_id)
        values = await self.catalog.list_agents(user_id)
        replacement = next(
            (value for value in values if value.agent_id != agent_id), None
        )
        if replacement is None:
            raise ValueError("Cannot delete the only agent")
        if agent.is_default:
            await self.catalog.save_agent(
                replacement.model_copy(update={"is_default": True})
            )
        await self.catalog.delete_agent(agent_id, user_id)

        settings = await self.get_settings()
        if settings.default_agent_id == agent_id:
            await self.save_settings(
                settings.model_copy(update={"default_agent_id": replacement.agent_id})
            )
        return await self.list_agents(user_id)

    async def list_mcp_connections(self, user_id: str) -> list[dict[str, Any]]:
        await self._initialize_user(user_id)
        values = await self.catalog.list_mcp(user_id)
        result = []
        for value in values:
            tool_count = 0
            connection_error = ""
            if not value.disabled:
                bridge = McpToolPlugin((self._mcp_config(value),))
                try:
                    tool_count = len(
                        await bridge.list_tools(run_id="desktop-mcp-catalog")
                    )
                except SageV2Error as exc:
                    connection_error = exc.info.message
            result.append(
                {
                    **value.model_dump(
                        mode="json",
                        exclude={"api_key", "user_id", "tools", "simulator"},
                    ),
                    "api_key_configured": bool(value.api_key),
                    "tool_count": tool_count,
                    "connection_error": connection_error,
                }
            )
        return result

    async def add_mcp_connection(
        self, request: MCPConnectionRequest, user_id: str
    ) -> dict[str, Any]:
        if request.protocol == "stdio" and not str(request.command or "").strip():
            raise ValueError("stdio connection requires command")
        if request.protocol == "sse" and not str(request.sse_url or "").strip():
            raise ValueError("sse connection requires URL")
        if (
            request.protocol == "streamable_http"
            and not str(request.streamable_http_url or "").strip()
        ):
            raise ValueError("streamable HTTP connection requires URL")
        await self.catalog.save_mcp(
            DesktopMcpRecord(
                user_id=user_id,
                name=request.name.strip(),
                protocol=request.protocol,
                streamable_http_url=request.streamable_http_url,
                sse_url=request.sse_url,
                api_key=request.api_key,
                command=request.command,
                args=tuple(request.args),
                env=request.env,
            )
        )
        values = await self.list_mcp_connections(user_id)
        return next(value for value in values if value["name"] == request.name.strip())

    async def set_mcp_connection_enabled(
        self, server_name: str, enabled: bool, user_id: str
    ) -> dict[str, Any]:
        record = next(
            (
                value
                for value in await self.catalog.list_mcp(user_id)
                if value.name == server_name
            ),
            None,
        )
        if record is None:
            raise ValueError("MCP connection not found")
        await self.catalog.save_mcp(record.model_copy(update={"disabled": not enabled}))
        values = await self.list_mcp_connections(user_id)
        return next(value for value in values if value["name"] == server_name)

    async def component_inventory(self, user_id: str) -> list[dict[str, Any]]:
        del user_id
        return list(self.extensions.inventory())

    async def select_component(
        self,
        component_id: str,
        request: ComponentSelectionRequest,
        user_id: str,
    ) -> dict[str, Any]:
        del user_id
        registration = self.extensions.get(request.plugin_id)
        capabilities = {offer.capability for offer in registration.descriptor.provides}
        if component_id not in capabilities:
            raise ValueError(
                f"extension {request.plugin_id!r} does not provide {component_id!r}"
            )
        settings = await self.get_settings()
        choices = dict(settings.component_selections)
        choices[component_id] = request.plugin_id
        await self.save_settings(
            settings.model_copy(update={"component_selections": choices})
        )
        return {
            "component_id": component_id,
            "plugin_id": request.plugin_id,
            "config": request.config,
            "pending_restart": True,
        }

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
            return DesktopV2Settings()
        return DesktopV2Settings.model_validate_json(
            self.settings_path.read_text(encoding="utf-8")
        )

    async def save_settings(self, value: DesktopV2Settings) -> DesktopV2Settings:
        workspace = await self._ensure_agent_workspace(value.agent_workspace_path)
        normalized = value.model_copy(
            update={
                "agent_workspace_path": str(workspace),
                "projects": [
                    self._normalize_project(project) for project in value.projects
                ],
            }
        )
        async with self._settings_lock:
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(normalized.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(self.settings_path)
        return normalized

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
            return await self._ensure_agent_workspace(settings.agent_workspace_path)
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

    async def _ensure_agent_workspace(self, configured: str) -> Path:
        workspace = self._agent_workspace_path(configured)
        try:
            await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"agent workspace cannot be created: {workspace}") from exc
        return workspace

    async def workspace_tree(
        self, workspace_id: str | None, agent_id: str
    ) -> list[dict[str, Any]]:
        root = await self.workspace_root(workspace_id, agent_id)
        settings = await self.get_settings()
        excluded: set[str] = set()
        if workspace_id and not workspace_id.startswith("agent:"):
            agent_workspace = await self._ensure_agent_workspace(
                settings.agent_workspace_path
            )
            excluded = await asyncio.to_thread(
                self._project_runtime_entries,
                root,
                agent_workspace,
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
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("invalid filename")
        uploads = root / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        target = self._resolve_child(uploads, safe_name)
        if target.exists():
            raise ValueError(f"upload already exists: {safe_name}")
        await asyncio.to_thread(target.write_bytes, content)
        return {
            "name": safe_name,
            "path": f"uploads/{safe_name}",
            "virtual_path": f"/workspace/uploads/{safe_name}",
            "size": len(content),
        }

    async def run_events(
        self, request: DesktopRunRequest, user_id: str
    ) -> AsyncIterator[str]:
        agent = await self._agent(request.agent_id, user_id)
        provider = await self._provider(agent, user_id)
        workspace = await self.workspace_root(request.workspace_id, request.agent_id)
        resolved, loop, sandbox_handle = await self._build_loop(
            agent=agent,
            provider=provider,
            workspace=workspace,
            preferred_skills=tuple(request.preferred_skills),
            approval_mode=request.approval_mode,
        )
        command = self._command(request, resolved, agent=agent, workspace=workspace)
        context = self._context(user_id)
        driver = _DesktopDriver(self, loop, workspace, sandbox_handle)
        facade = SAgent(runtime=self.runtime, driver_factory=lambda _run_id: driver)
        stream = await facade.run_stream(command, context)
        await self._index_session(stream.handle.session_id)
        self._drivers[stream.handle.run_id] = driver
        stream._execution.add_done_callback(
            lambda _completed, key=stream.handle.run_id, value=driver: (
                self._discard_driver(key, value)
            )
        )
        yield (
            json.dumps(
                {
                    "kind": "stream.opened",
                    "handle": stream.handle.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        observed_boundary = False
        try:
            async for event in stream.events:
                yield event.model_dump_json() + "\n"
            observed_boundary = True
        finally:
            if observed_boundary:
                await stream.wait()
            if stream._execution.done():
                self._drivers.pop(stream.handle.run_id, None)
            await self._index_session(stream.handle.session_id)

    async def snapshot(self, run_id: str) -> dict[str, Any]:
        run = await self.runtime.get_run(run_id)
        data: dict[str, Any] = {"run": run.model_dump(mode="json")}
        if run.suspension_id:
            suspension = await self.session_store.get_suspension(run.suspension_id)
            data["suspension"] = suspension.model_dump(mode="json")
            if suspension.interaction_id:
                interaction = await self.session_store.get_interaction(
                    suspension.interaction_id
                )
                data["interaction"] = interaction.model_dump(mode="json")
        return data

    async def _index_session(self, session_id: str) -> None:
        """Publish one known Session into the Desktop-owned global index."""

        try:
            await self.session_index.upsert(
                await self.session_store.get_session(session_id)
            )
        except Exception:
            # The product index is downstream of the authoritative commit. It
            # may be rebuilt or repaired without changing the Session journal.
            LOGGER.exception("Desktop Session index update failed for %s", session_id)

    async def _index_run(self, run_id: str) -> None:
        run = await self.session_store.get_run(run_id)
        await self._index_session(run.session_id)

    async def subscribe_events(
        self, run_id: str, after_sequence: int
    ) -> AsyncIterator[str]:
        async for event in self.runtime.subscribe_events(
            EventCursor(run_id=run_id, run_sequence=after_sequence)
        ):
            yield event.model_dump_json() + "\n"
            if event.type in {
                "run.suspended",
                "run.completed",
                "run.failed",
                "run.cancelled",
            }:
                await self._index_run(run_id)
                return

    async def pause(self, run_id: str, user_id: str):
        run = await self.runtime.get_run(run_id)
        result = await self.runtime.pause_run(
            PauseRun(
                run_id=run_id,
                expected_revision=run.revision,
                idempotency_key=new_id("pause"),
            ),
            self._context(user_id),
        )
        await self._index_session(run.session_id)
        return result

    async def cancel(self, run_id: str, user_id: str):
        run = await self.runtime.get_run(run_id)
        result = await self.runtime.cancel_run(
            CancelRun(
                run_id=run_id,
                expected_revision=run.revision,
                idempotency_key=new_id("cancel"),
            ),
            self._context(user_id),
        )
        await self._index_session(run.session_id)
        return result

    async def steer(self, run_id: str, turn_id: str, text: str, user_id: str):
        run = await self.runtime.get_run(run_id)
        result = await self.runtime.steer_run(
            SteerRun(
                run_id=run_id,
                expected_revision=run.revision,
                expected_turn_id=turn_id,
                input=(InputItem(role="user", content=(TextBlock(text=text),)),),
                idempotency_key=new_id("steer"),
            ),
            self._context(user_id),
        )
        await self._index_session(run.session_id)
        return result

    async def resume(self, run_id: str, user_id: str):
        run = await self.runtime.get_run(run_id)
        if run.suspension_id is None:
            raise ValueError("run has no suspension")
        suspension = await self.session_store.get_suspension(run.suspension_id)
        receipt = await self.runtime.resume_run(
            ResumeRun(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                expected_revision=run.revision,
                expected_suspension_revision=suspension.expected_revision,
                idempotency_key=new_id("resume"),
            ),
            self._context(user_id),
        )
        if receipt.decision.value != "rejected":
            await self._continue(run_id, user_id)
        await self._index_session(run.session_id)
        return receipt

    async def reply_interaction(
        self,
        run_id: str,
        interaction_id: str,
        decision: str,
        payload: dict[str, Any],
        user_id: str,
    ):
        run = await self.runtime.get_run(run_id)
        if run.suspension_id is None:
            raise ValueError("run has no suspension")
        suspension = await self.session_store.get_suspension(run.suspension_id)
        interaction = await self.session_store.get_interaction(interaction_id)
        receipt = await self.runtime.reply_interaction(
            ReplyInteraction(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction_id,
                expected_revision=run.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision=decision,
                payload=payload,
                idempotency_key=new_id("interaction"),
            ),
            self._context(user_id),
        )
        if receipt.decision.value != "rejected":
            await self._continue(run_id, user_id)
        await self._index_session(run.session_id)
        return receipt

    async def _continue(self, run_id: str, user_id: str) -> None:
        driver = self._drivers.get(run_id)
        if driver is None:
            command = await self.session_store.get_start_command(run_id)
            agent = await self._agent(command.agent_id, user_id)
            provider = await self._provider(agent, user_id)
            workspace_id = command.config.metadata.get("workspace_id")
            workspace = await self.workspace_root(workspace_id, command.agent_id)
            _, loop, sandbox_handle = await self._build_loop(
                agent=agent,
                provider=provider,
                workspace=workspace,
                preferred_skills=tuple(
                    command.config.metadata.get("preferred_skills") or ()
                ),
                approval_mode=str(
                    command.config.metadata.get("approval_mode") or "high_risk"
                ),
            )
            driver = _DesktopDriver(self, loop, workspace, sandbox_handle)
            self._drivers[run_id] = driver
        facade = SAgent(runtime=self.runtime, driver_factory=lambda _: driver)
        task = await facade.continue_run(run_id, self._context(user_id))
        task.add_done_callback(
            lambda _completed, key=run_id, value=driver: self._discard_driver(
                key, value
            )
        )
        task.add_done_callback(
            lambda _completed, key=run_id: asyncio.create_task(self._index_run(key))
        )

    def _discard_driver(self, run_id: str, driver: _DesktopDriver) -> None:
        if self._drivers.get(run_id) is driver:
            self._drivers.pop(run_id, None)

    async def _build_loop(
        self,
        *,
        agent,
        provider,
        workspace,
        preferred_skills,
        approval_mode,
    ):
        skill_provider = self._skill_provider()
        mcp_plugin = await self._mcp_plugin(agent.user_id)
        mcp_definitions = await mcp_plugin.list_tools(run_id="desktop-composition")
        valid_skills = tuple(
            value
            for value in (agent.config.get("availableSkills") or ())
            if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
        )
        configured_tools = agent.config.get("availableTools")
        valid_tools = tuple(
            value
            for value in (
                configured_tools
                if configured_tools is not None
                else tuple(
                    value["name"] for value in await self.list_tools(agent.user_id)
                )
            )
            if isinstance(value, str) and _TOOL_NAME.fullmatch(value)
        )
        known_tools = {
            value.name
            for value in (
                *self._native_tool_definitions(),
                *mcp_definitions,
            )
        }
        missing_tools = sorted(set(valid_tools) - known_tools)
        if missing_tools:
            raise ValueError(
                "configured tools are unavailable: " + ", ".join(missing_tools)
            )
        if valid_skills and "load_skill" not in valid_tools:
            valid_tools = (*valid_tools, "load_skill")
        manifest = self._manifest(agent, provider, valid_tools, valid_skills)
        resolved = CompositionResolver().resolve(manifest)
        settings = await self.get_settings()
        estimator_id = settings.component_selections.get(
            "context.token-estimator", "json-heuristic"
        )
        reducer_id = settings.component_selections.get(
            "context.reducer", "persistent-summary"
        )
        # Desktop compression uses the configured route itself. The summary is
        # derived state in SummaryStore; canonical Session events remain intact.
        # Recording the secondary request also keeps provider diagnostics honest.
        model_provider = self._model_provider(provider, agent)
        recording_model = RecordingModelProvider(
            model_provider,
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "provider_id": provider.id,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
            },
        )
        factory = AgentRuntimeFactory(
            self.runtime,
            context_components=ContextComponentBundle(
                token_estimator=TokenEstimatorRegistry().create(estimator_id),
                summary_store=self.summary_store,
                summarizer=ModelConversationSummarizer(recording_model),
                reducer_id=reducer_id,
            ),
        )
        agent_workspace = await self._ensure_agent_workspace(
            settings.agent_workspace_path
        )
        loader = factory.create_skill_loader(
            resolved,
            agent.agent_id,
            catalog=skill_provider,
            source=skill_provider,
            workspace=LocalSkillWorkspace(agent_workspace),
            activations=self.activations,
            workspace_root="/workspace",
        )
        issuer = SandboxGrantIssuer()
        sandbox_provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
        fingerprint = hashlib.sha256(str(workspace).encode()).hexdigest()
        sandbox_handle = await sandbox_provider.provision(
            ResolvedSandboxSpec(
                spec_hash=f"sha256:{fingerprint}",
                architecture="native",
                filesystem=FileSystemPolicy(
                    allowed_operations=frozenset(FileOperation),
                    max_file_bytes=64 * 1024 * 1024,
                    max_total_bytes=4 * 1024 * 1024 * 1024,
                ),
                process=ProcessPolicy(
                    enabled=True,
                    allowed_executables=(
                        "git",
                        "rg",
                        "python",
                        "python3",
                        "pytest",
                        "flutter",
                        "dart",
                        "npm",
                        "node",
                        "bash",
                        "sh",
                    ),
                    allowed_env_names=("PATH", "PYTHONPATH"),
                    max_wall_time_seconds=300,
                    max_output_bytes=4 * 1024 * 1024,
                ),
                network=NetworkPolicy(),
                policy_hash=f"sha256:{fingerprint}",
                metadata={"host_workspace": str(workspace)},
            ),
            self._context(agent.user_id),
            run_id=new_id("desktop_sandbox"),
        )
        official_tools = self._official_tools(
            OfficialToolRuntime(sandbox_handle, issuer)
        )
        skill_tool = SkillToolPlugin(loader)
        catalogs = (
            official_tools.catalog,
            skill_tool.catalog,
        )
        executors = (
            official_tools.executor,
            skill_tool.executor,
        )
        if mcp_definitions:
            catalogs = (*catalogs, mcp_plugin)
            executors = (*executors, mcp_plugin)
        native_catalog = CompositeToolCatalog(catalogs)
        native_executor = CompositeToolExecutor(executors)
        loop = factory.create_loop(
            resolved,
            agent.agent_id,
            model=recording_model,
            tool_catalog=native_catalog,
            tool_executor=native_executor,
            tool_policy=DefaultToolPolicy(
                approval_strategy=ApprovalStrategy(approval_mode),
            ),
            skill_loader=loader,
        )
        loop.context_assembler.providers = (
            *loop.context_assembler.providers,
            PreferredSkillsContextProvider(),
        )
        return resolved, loop, sandbox_handle

    async def _session_id_for_run(self, run_id: str) -> str:
        return (await self.session_store.get_run(run_id)).session_id

    def _manifest(self, agent, provider, tools, skills):
        max_steps = max(1, min(int(agent.config.get("maxLoopCount") or 24), 200))
        deep_thinking, thinking_level = self._thinking_config(agent)
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=provider.max_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=thinking_level if deep_thinking else None,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=provider.max_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=True,
                reasoning=True,
                parallel_tool_calls=True,
            ),
        )
        return SageManifest(
            kind="agent-package",
            metadata=ManifestMetadata(
                id=f"desktop.{agent.agent_id}",
                version="0.1.0",
                name=agent.name,
                description=agent.config.get("description"),
            ),
            credentials={
                "desktop_model": CredentialDeclaration(
                    source="host", ref=f"llm-provider:{provider.id}"
                )
            },
            models={"primary": route},
            policies=PolicyConfig(budgets={"max_steps": max_steps}),
            agents={
                agent.agent_id: AgentDefinition(
                    name=agent.name,
                    instructions=Instructions(
                        inline=agent.config.get("systemPrefix")
                        or "You are a helpful Sage agent."
                    ),
                    models={"primary": "primary"},
                    tools=tools,
                    skills=skills,
                    budgets=AgentBudgets(max_steps=max_steps),
                )
            },
            entrypoint=ApplicationEntrypoint(agent=agent.agent_id),
        )

    def _model_provider(self, provider, agent):
        model_lower = provider.model.lower()
        max_field = (
            "max_completion_tokens"
            if model_lower.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        deep_thinking, thinking_level = self._thinking_config(agent)
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=provider.max_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=thinking_level if deep_thinking else None,
                extra=(
                    {"max_output_tokens_field": max_field}
                    if provider.protocol == "openai-chat-completions"
                    else {}
                ),
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=provider.max_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=True,
                reasoning=True,
                parallel_tool_calls=True,
            ),
        )
        protocol = resolve_model_protocol(route.provider)
        registration = self.extensions.get(f"sage.model.{protocol.value}")
        return registration.factory(
            ExtensionScopeContext(
                scope=ExtensionScope.AGENT,
                scope_id=f"desktop-agent:{agent.agent_id}",
                agent_id=agent.agent_id,
                config={
                    "route": route.model_dump(mode="json"),
                    "credential": CredentialMaterial(
                        credential_id=f"llm-provider:{provider.id}",
                        secret=SecretStr(provider.api_key or ""),
                        source="desktop-catalog",
                    ),
                    "provider_instance_id": provider.id,
                },
            ),
            {},
        )

    @staticmethod
    def _thinking_config(agent) -> tuple[bool, str]:
        enabled = bool(
            agent.config.get("deepThinking", agent.config.get("deep_thinking", False))
        )
        level = str(
            agent.config.get("thinkingLevel")
            or agent.config.get("thinking_level")
            or "medium"
        ).lower()
        if level not in {"minimal", "low", "medium", "high", "xhigh", "max"}:
            level = "medium"
        return enabled, level

    def _command(
        self, request: DesktopRunRequest, resolved, *, agent=None, workspace=None
    ):
        current_time = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
        frozen_time = f"<current_time>{current_time}</current_time>"
        items = tuple(
            InputItem(
                role=value.role,
                content=(TextBlock(text=value.text),),
                metadata=(
                    {"frozen_current_time_context": frozen_time}
                    if value.role == "user"
                    else {}
                ),
            )
            for value in request.messages
            if value.text.strip()
        )
        if request.attachment_paths:
            items = (
                *items,
                InputItem(
                    role="user",
                    content=(
                        TextBlock(
                            text="Attached workspace references (files or directories):\n"
                            + "\n".join(request.attachment_paths)
                        ),
                    ),
                    metadata={"frozen_current_time_context": frozen_time},
                ),
            )
        configured_context = {}
        if agent is not None:
            raw_context = agent.config.get("systemContext") or agent.config.get(
                "system_context"
            )
            if isinstance(raw_context, dict):
                configured_context = dict(raw_context)
        response_language = str(
            configured_context.pop("response_language", "zh") or "zh"
        )
        metadata = {
            "workspace_id": request.workspace_id,
            "preferred_skills": request.preferred_skills,
            "approval_mode": request.approval_mode,
            "response_language": response_language,
            "system_context": configured_context,
            "current_time": current_time,
            "identity_documents": self._identity_documents(
                self._agent_workspace_path(
                    self._read_settings_sync().agent_workspace_path
                )
            ),
        }
        if workspace is not None:
            resolved_workspace = Path(workspace).resolve()
            metadata["working_directory"] = str(resolved_workspace)
            metadata["workspace_files"] = self._workspace_prompt_listing(
                resolved_workspace
            )
        for key in ("todo", "external_paths", "shell_completion_reminder"):
            if key in configured_context:
                metadata[key] = configured_context.pop(key)
        run_config = CompositionResolver().resolve_run_config(
            resolved,
            request.agent_id,
            metadata=metadata,
        )
        return StartRun(
            session_id=request.session_id,
            agent_id=request.agent_id,
            input=items,
            config=run_config,
            resolved_spec_hash=resolved.manifest_hash,
            idempotency_key=request.idempotency_key or new_id("desktop_request"),
            session_concurrency_mode=request.session_concurrency_mode,
            base_session_revision=request.base_session_revision,
        )

    def _identity_documents(self, root: Path | None = None) -> dict[str, str]:
        values = {}
        workspace = (root or self.agent_workspace).resolve()
        for name in ("AGENT", "IDENTITY", "SOUL", "USER", "MEMORY"):
            path = workspace / f"{name}.md"
            if not path.is_file() or path.is_symlink():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if content.strip():
                values[name] = content[:200_000]
        return values

    @staticmethod
    def _workspace_prompt_listing(root: Path, *, maximum: int = 200) -> str:
        """Freeze a deterministic, bounded two-level workspace view for one Run."""

        entries = []
        for candidate in sorted(root.rglob("*")):
            relative = candidate.relative_to(root)
            if len(relative.parts) > 2 or candidate.is_symlink():
                continue
            suffix = "/" if candidate.is_dir() else ""
            entries.append(relative.as_posix() + suffix)
            if len(entries) >= maximum:
                entries.append("... (truncated)")
                break
        return (
            "Working directory: "
            + str(root)
            + "\n"
            + ("\n".join(entries) if entries else "(Empty)")
        )

    async def _agent(self, agent_id: str, user_id: str) -> DesktopAgentRecord:
        await self._initialize_user(user_id)
        agent = await self.catalog.get_agent(agent_id, user_id)
        if agent is None:
            raise ValueError("agent is not configured for this Desktop user")
        return agent

    async def _provider(
        self, agent: DesktopAgentRecord, user_id: str
    ) -> DesktopModelProviderRecord:
        provider_id = agent.config.get("llm_provider_id")
        provider = (
            await self.catalog.get_model_provider(str(provider_id), agent.user_id)
            if provider_id
            else None
        )
        values = await self.catalog.list_model_providers(user_id)
        if provider is None:
            provider = next((value for value in values if value.is_default), None)
        if provider is None and values:
            provider = values[0]
        if provider is None or not provider.api_key or not provider.base_url:
            raise ValueError("agent has no usable model provider")
        return provider

    async def _initialize_user(self, user_id: str) -> None:
        initialize = getattr(self.catalog, "initialize_user", None)
        if initialize is not None:
            await initialize(user_id)
        if self.legacy_db_path is None or user_id in self._legacy_imported_users:
            return
        async with self._legacy_import_lock:
            if user_id in self._legacy_imported_users:
                return
            imported = await asyncio.to_thread(
                read_legacy_desktop_settings,
                self.legacy_db_path,
                target_user_id=user_id,
            )
            existing = await self.catalog.list_model_providers(user_id)
            existing_ids = {value.id for value in existing}
            placeholder = next(
                (
                    value
                    for value in existing
                    if value.id == "model_main"
                    and not value.api_key
                    and value.name == "OpenAI"
                ),
                None,
            )
            for value in imported.model_providers:
                if value.id not in existing_ids:
                    await self.catalog.save_model_provider(value)
            imported_default = next(
                (value for value in imported.model_providers if value.is_default),
                imported.model_providers[0] if imported.model_providers else None,
            )
            if placeholder is not None and imported.model_providers:
                await self.catalog.delete_model_provider(
                    placeholder.id, placeholder.user_id
                )
                if imported_default is not None:
                    for agent in await self.catalog.list_agents(user_id):
                        config = dict(agent.config)
                        if config.get("llm_provider_id") == placeholder.id:
                            config["llm_provider_id"] = imported_default.id
                            await self.catalog.save_agent(
                                agent.model_copy(update={"config": config})
                            )
            for value in imported.mcp_connections:
                current = await self.catalog.list_mcp(user_id)
                if not any(item.name == value.name for item in current):
                    await self.catalog.save_mcp(value)
            self._legacy_imported_users.add(user_id)

    def _skill_provider(self) -> FilesystemSkillProvider:
        repository_skills = Path(__file__).resolve().parents[3] / "skills"
        return FilesystemSkillProvider((self.skill_root, repository_skills))

    @staticmethod
    def _skill_name(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^name:\s*['\"]?([^'\"\n]+)", text)
        name = match.group(1).strip() if match else path.parent.name
        if not _SKILL_NAME.fullmatch(name) or name in {".", ".."}:
            raise ValueError("SKILL.md must define a valid name")
        return name

    @staticmethod
    def _context(user_id: str) -> RequestContext:
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
            )
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
    def _project_runtime_entries(
        cls,
        project_root: Path,
        agent_workspace: Path,
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
        source_skills = Path(os.environ.get("SAGE_SKILL_WORKSPACE", "")).expanduser()
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
