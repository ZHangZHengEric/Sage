from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import posixpath
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from sagents.llm.model_capabilities import build_llm_extra_body
from app.desktop_v2.backend.catalog import (
    DesktopAgentRecord,
    DesktopCatalogStore,
    DesktopMcpRecord,
    DesktopModelProviderRecord,
    JsonDesktopCatalogStore,
    default_agent_config,
)
from app.desktop_v2.backend.shell_policy import (
    ShellCommandOperationAssessor,
    normalize_shell_command,
    shell_policy_summary,
)
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from sagents.v2.tool.localization import localize_tool_definition
from app.desktop_v2.backend.session_index import JsonDesktopSessionIndex
from sagents.v2 import SAgent
from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    SessionDynamicAgentRoster,
    WorkspaceSharingPolicy,
)
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
    OfficialToolRuntime,
    official_tool_categories,
    official_tool_definitions,
)
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    RunConfig,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import (
    EventCursor,
    SessionConcurrencyMode,
    TERMINAL_RUN_STATES,
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionMergeStrategy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.agent import AgentCompositionFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.package.manifest.agents import (
    AgentBudgets,
    AgentDefinition,
    AgentMemoryBehavior,
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
from sagents.v2.context import (
    ContextBudget,
    ContextSegment,
    ContextStability,
    DefaultContextAssembler,
    RunMetadataContextProvider,
    TokenEstimatorRegistry,
)
from sagents.v2.goal import (
    GoalCompletionGatePolicy,
    GoalContextProvider,
    GoalStateService,
)
from sagents.v2.i18n import normalize_language
from sagents.v2.plan import (
    PlanCompletionGatePolicy,
    PlanContextProvider,
)
from sagents.v2.memory import MemoryService
from sagents.v2.session_memory import SessionMemoryService
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
    FileSystemMode,
    FileOperation,
    FileSystemPolicy,
    NetworkPolicy,
    OperationIntent,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
    SandboxHandle,
)
from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
    FilesystemSkillProvider,
    SessionDerivedSkillActivationRepository,
    SkillLoadTool,
)
from sagents.v2.tool import decorated_tool_definition
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.runtime.observability import (
    LogError,
    LogLevel,
    LogRecord,
    LogSink,
    StructuredLogger,
)
from sagents.v2.skill.contracts import SkillBundle
from sagents.v2.tool import (
    CompositeToolCatalog,
    CompositeToolExecutor,
    McpServerConfig,
    McpToolPlugin,
    ToolDefinition,
    ToolSelectionConfig,
)
from app.desktop_v2.backend.observability import create_desktop_log_sink


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


_TOOL_CATEGORY_SOURCES = {
    "code_quality": "代码质量",
    "code_search": "代码检索",
    "files": "文件",
    "image": "图像",
    "interaction": "交互",
    "memory": "记忆",
    "multi_agent": "多智能体",
    "planning": "任务规划",
    "shell": "终端",
    "system": "系统",
    "web": "网页",
}


def _tool_category_source(category: str | None) -> str:
    if not category:
        return "基础工具"
    return _TOOL_CATEGORY_SOURCES.get(category, f"分类: {category}")


def _normalized_assignment_names(values: list[str] | None, *, label: str) -> list[str]:
    """Return deterministic Tool/Skill assignments without blank identities."""

    normalized = [str(value).strip() for value in values or ()]
    if any(not value for value in normalized):
        raise ValueError(f"{label} names cannot be empty")
    return sorted(set(normalized))


def _agent_memory_enabled(
    agent: Any, memory_plugin_id: str, session_memory_plugin_id: str
) -> bool:
    """Use Tool assignment as the per-Agent Memory feature switch."""

    has_provider = (
        memory_plugin_id != "sage.memory.noop"
        or session_memory_plugin_id != "sage.session-memory.noop"
    )
    return has_provider and "search_memory" in set(
        agent.config.get("availableTools") or ()
    )


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
    component_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ComponentSelectionRequest(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=192)
    config: dict[str, Any] = Field(default_factory=dict)


_DESKTOP_COMPONENTS = {
    "agent.continuation-policy": {
        "default": "sage.agent.continuation.deterministic",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "run",
    },
    "context.token-estimator": {
        "default": "sage.context.token-estimator.json-heuristic",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "tenant",
    },
    "context.reducer": {
        "default": "sage.context.reducer.persistent-summary",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "tenant",
    },
    "context.summarizer": {
        "default": "sage.context.summarizer.model",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "context.summary-store": {
        "default": "sage.context.summary-store.session-derived",
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "memory.provider": {
        "default": "sage.memory.filesystem-bm25",
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "memory.recall-query": {
        "default": "sage.memory.recall-query.direct",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "tool.selection-policy": {
        "default": "sage.tool-selection.llm",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "session-memory.provider": {
        "default": "sage.session-memory.sqlite-bm25",
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "observability.diagnostic-sink": {
        "default": "sage.observability.filesystem",
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "observability.log-sink": {
        "default": "sage.logging.filesystem",
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "execution.sandbox": {
        "default": "sage.sandbox.local-workspace",
        "selection_mode": "host",
        "apply_mode": "next_run",
        "scope": "run",
    },
    "session.store": {
        "default": "sage.session.filesystem",
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "workspace.initializer": {
        "default": "sage.workspace.initializer.claw",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
}
_DESKTOP_COMPONENT_DEFAULTS = {
    capability: str(spec["default"]) for capability, spec in _DESKTOP_COMPONENTS.items()
}
_CONTINUATION_COMPONENT_CHOICES = (
    "sage.agent.continuation.explicit-status",
    "sage.agent.continuation.llm-judge",
    "sage.agent.continuation.deterministic",
)


def _continuation_component_config(plugin_id: str) -> dict[str, Any]:
    shared = {
        "repeat_threshold": 3,
        "status_source": "turn_status",
        "explicit_statuses": [
            "task_done",
            "need_user_input",
            "blocked",
            "continue_work",
            "failed",
        ],
        "flow_boundaries": ["complete_node", "continue_node"],
        "uses_finish_reason": False,
    }
    if plugin_id == "sage.agent.continuation.llm-judge":
        return {
            **shared,
            "mode": "llm_judge",
            "model_binding": "fast",
            "prompt_contract": "v1",
            "decisions": [
                "continue",
                "completed",
                "need_user_input",
                "blocked",
            ],
            "uses_confidence": False,
            "status_source": "none",
            "explicit_statuses": [],
            "uses_llm_judge": True,
            "judge_failure": "continue",
        }
    if plugin_id == "sage.agent.continuation.hybrid":
        return {
            **shared,
            "mode": "hybrid",
            "model_binding": "fast",
            "prompt_contract": "v1",
            "uses_confidence": False,
            "uses_llm_judge": True,
            "judge_failure": "deterministic_fallback",
        }
    if plugin_id == "sage.agent.continuation.explicit-status":
        return {
            **shared,
            "mode": "explicit_status",
            "requires_explicit_status": True,
            "uses_llm_judge": False,
        }
    return {
        **shared,
        "mode": "deterministic",
        "completion_reason": "text.final",
        "uses_llm_judge": False,
    }


def _tool_selection_component_config(
    plugin_id: str, raw_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Normalize official configs while preserving plugin-defined parameters."""

    if plugin_id == "sage.tool-selection.direct":
        return {}
    if plugin_id in {
        "sage.tool-selection.llm",
        "sage.tool-selection.lexical",
        "sage.tool-selection.recent",
    }:
        return ToolSelectionConfig.model_validate(raw_config or {}).model_dump(
            mode="json"
        )
    return dict(raw_config or {})


def _continuation_agent_instructions(plugin_id: str) -> str:
    if plugin_id == "sage.agent.continuation.explicit-status":
        return (
            "\n\nRuntime completion policy: explicit turn status is required. "
            "Before ending every response, call turn_status with task_done, "
            "continue_work, need_user_input, blocked, or failed. Ordinary final "
            "text without turn_status does not finish the Run."
        )
    return ""


_SANDBOX_DEFAULTS = {
    "sage.sandbox.local-workspace": {
        "workspace_root": "/workspace",
        "workspace_path_mode": "virtual",
        "workspace_mapping": "active_workspace",
        "filesystem_mode": "workspace",
    },
    "sage.sandbox.ephemeral": {
        "workspace_root": "/workspace",
        "workspace_path_mode": "virtual",
        "workspace_mapping": "isolated",
        "filesystem_mode": "workspace",
    },
}


def _virtual_workspace_root(value: Any) -> str:
    raw = str(value or "/workspace").strip().replace("\\", "/")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/") or normalized == "/" or ".." in raw.split("/"):
        raise ValueError("sandbox workspace_root must be a contained absolute path")
    return normalized


def _resolved_sandbox_config(
    settings: DesktopV2Settings,
) -> tuple[str, dict[str, Any]]:
    plugin_id = _stable_component_id(
        "execution.sandbox",
        settings.component_selections.get(
            "execution.sandbox",
            _DESKTOP_COMPONENT_DEFAULTS["execution.sandbox"],
        ),
    )
    config = dict(_SANDBOX_DEFAULTS.get(plugin_id, {}))
    config.update(settings.component_configs.get("execution.sandbox", {}))
    config["workspace_root"] = _virtual_workspace_root(config.get("workspace_root"))
    path_mode = str(config.get("workspace_path_mode", "virtual"))
    if path_mode not in {"virtual", "host"}:
        raise ValueError("sandbox workspace_path_mode must be virtual or host")
    mapping = str(config.get("workspace_mapping", "isolated"))
    if mapping not in {"active_workspace", "isolated"}:
        raise ValueError(
            "sandbox workspace_mapping must be active_workspace or isolated"
        )
    if plugin_id == "sage.sandbox.local-workspace" and mapping != "active_workspace":
        raise ValueError("local-workspace sandbox requires active_workspace mapping")
    if plugin_id == "sage.sandbox.ephemeral" and mapping != "isolated":
        raise ValueError("ephemeral sandbox cannot map the active workspace")
    if mapping == "isolated" and path_mode != "virtual":
        raise ValueError("isolated sandbox requires a fixed virtual workspace path")
    config["workspace_path_mode"] = path_mode
    config["workspace_mapping"] = mapping
    try:
        config["filesystem_mode"] = FileSystemMode(
            str(config.get("filesystem_mode", "workspace"))
        ).value
    except ValueError as exc:
        raise ValueError("sandbox filesystem_mode is invalid") from exc
    return plugin_id, config


def _sandbox_workspace_root(
    config: dict[str, Any], host_workspace: Path | None = None
) -> str:
    if config.get("workspace_path_mode") != "host":
        return str(config["workspace_root"])
    if config.get("workspace_mapping") != "active_workspace":
        raise ValueError("host workspace path mode requires active workspace mapping")
    if host_workspace is None:
        raise ValueError("host workspace path mode requires the active workspace")
    return _virtual_workspace_root(host_workspace.expanduser().resolve().as_posix())


def _runtime_component_id(capability: str, plugin_id: str) -> str:
    """Translate stable extension IDs to the short constructor IDs used by v2."""

    prefixes = {
        "agent.continuation-policy": "sage.agent.continuation.",
        "context.token-estimator": "sage.context.token-estimator.",
        "context.reducer": "sage.context.reducer.",
        "context.summarizer": "sage.context.summarizer.",
        "context.summary-store": "sage.context.summary-store.",
        "memory.provider": "sage.memory.",
        "memory.recall-query": "sage.memory.recall-query.",
        "session-memory.provider": "sage.session-memory.",
        "observability.diagnostic-sink": "sage.observability.",
        "observability.log-sink": "sage.logging.",
        "execution.sandbox": "sage.sandbox.",
        "session.store": "sage.session.",
        "workspace.initializer": "sage.workspace.initializer.",
        "tool.selection-policy": "sage.tool-selection.",
    }
    prefix = prefixes[capability]
    return plugin_id.removeprefix(prefix)


def _stable_component_id(capability: str, plugin_id: str) -> str:
    """Accept settings written before Desktop exposed stable extension IDs."""

    if capability == "agent.continuation-policy" and plugin_id in {
        "hybrid",
        "sage.agent.continuation.hybrid",
    }:
        # Hybrid was an implementation composition, not a distinct completion
        # signal. Keep its backend plugin for package compatibility while
        # migrating the former Desktop choice to the Judge mode.
        return "sage.agent.continuation.llm-judge"
    if capability == "tool.selection-policy" and plugin_id in {
        "hybrid",
        "sage.tool-selection.hybrid",
    }:
        return "sage.tool-selection.llm"
    if plugin_id.startswith("sage."):
        return plugin_id
    prefixes = {
        "agent.continuation-policy": "sage.agent.continuation.",
        "context.token-estimator": "sage.context.token-estimator.",
        "context.reducer": "sage.context.reducer.",
        "context.summarizer": "sage.context.summarizer.",
        "context.summary-store": "sage.context.summary-store.",
        "memory.provider": "sage.memory.",
        "memory.recall-query": "sage.memory.recall-query.",
        "session-memory.provider": "sage.session-memory.",
        "observability.diagnostic-sink": "sage.observability.",
        "observability.log-sink": "sage.logging.",
        "execution.sandbox": "sage.sandbox.",
        "session.store": "sage.session.",
        "workspace.initializer": "sage.workspace.initializer.",
        "tool.selection-policy": "sage.tool-selection.",
    }
    return prefixes[capability] + plugin_id


class AgentSettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    system_prefix: str | None = Field(default=None, max_length=20_000)
    runtime_variables: dict[str, Any] | None = None
    system_context: dict[str, Any] | None = None  # Legacy API alias.
    llm_provider_id: str | None = None
    fast_llm_provider_id: str | None = None
    agent_mode: Literal["simple", "fibre", "team"] | None = None
    sub_agent_selection_mode: Literal["auto_all", "manual"] | None = None
    available_sub_agent_ids: list[str] | None = None
    max_loop_count: int | None = Field(default=None, ge=1, le=10_000)
    deep_thinking: bool | None = None
    thinking_level: (
        Literal["minimal", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    available_tools: list[str] | None = None
    available_skills: list[str] | None = None
    approved_shell_commands: list[str] | None = None

    model_config = {"extra": "forbid"}


class AgentCreate(BaseModel):
    """Create an independently persisted Agent from the default template."""

    name: str = Field(min_length=1, max_length=255)
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
    response_language: str | None = None
    preferred_skills: list[str] = Field(default_factory=list)
    attachment_paths: list[str] = Field(default_factory=list)
    approval_mode: Literal["always_ask", "high_risk", "auto_approve"] = "high_risk"
    invocation_mode: Literal["normal", "plan", "goal"] = "normal"
    plan_mode: bool | None = None
    idempotency_key: str | None = None
    session_concurrency_mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL
    base_session_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def migrate_legacy_plan_mode(self):
        if self.plan_mode is True:
            if self.invocation_mode not in {"normal", "plan"}:
                raise ValueError("plan_mode conflicts with invocation_mode")
            self.invocation_mode = "plan"
        return self


class LocalSkillWorkspace:
    """Materialize exactly one Skill after an explicit load_skill call."""

    def __init__(self, root: Path, *, workspace_root: str = "/workspace") -> None:
        self.root = root.resolve()
        self.workspace_root = _virtual_workspace_root(workspace_root)
        self._lock = asyncio.Lock()

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        del run_id
        prefix = self.workspace_root.rstrip("/") + "/"
        if not destination.startswith(prefix):
            raise PermissionError("skill destination is outside the active workspace")
        relative = destination.removeprefix(prefix).lstrip("/")
        target = (self.root / relative).resolve()
        if self.root != target and self.root not in target.parents:
            raise PermissionError("skill destination is outside the active workspace")
        async with self._lock:
            await asyncio.to_thread(self._materialize_sync, bundle, target)
        return self.workspace_root.rstrip("/") + f"/{relative}"

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


class SandboxSkillWorkspace:
    """Materialize Skill bundles inside an isolated sandbox namespace."""

    def __init__(self, sandbox: SandboxHandle, issuer: SandboxGrantIssuer) -> None:
        self.sandbox = sandbox
        self.issuer = issuer
        self._lock = asyncio.Lock()
        self._operation_index = 0

    def _intent(self, run_id: str, operation: FileOperation, path: str):
        self._operation_index += 1
        intent = OperationIntent(
            operation=operation.value,
            run_id=run_id,
            tool_call_id=f"skill_materialize_{self._operation_index}",
            sandbox_id=self.sandbox.ref.sandbox_id,
            path=path,
        )
        return intent, self.issuer.issue(
            ref=self.sandbox.ref,
            intent=intent,
            allowed_operations=frozenset({operation.value}),
        )

    async def _read_optional(self, path: str, run_id: str) -> bytes | None:
        intent, grant = self._intent(run_id, FileOperation.READ, path)
        try:
            return await self.sandbox.filesystem.read_bytes(
                path, intent=intent, grant=grant
            )
        except FileNotFoundError:
            return None

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        destination = self.sandbox.filesystem.normalize_path(destination)
        async with self._lock:
            missing: list[tuple[str, bytes]] = []
            for relative, content in bundle.files.items():
                path = destination.rstrip("/") + f"/{relative}"
                existing = await self._read_optional(path, run_id)
                if existing is None:
                    missing.append((path, content))
                elif existing != content:
                    raise PermissionError(
                        f"workspace skill {bundle.descriptor.name!r} conflicts "
                        "with existing sandbox content"
                    )
            for path, content in missing:
                intent, grant = self._intent(run_id, FileOperation.CREATE, path)
                await self.sandbox.filesystem.write_bytes(
                    path,
                    content,
                    intent=intent,
                    grant=grant,
                    overwrite=False,
                )
        return destination


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


class AgentRosterContextProvider:
    """Expose exact multi-Agent identities and mode semantics to the model."""

    def __init__(
        self,
        registry: AgentRegistry,
        mode: AgentMode,
        *,
        allow_delegation: bool = True,
    ) -> None:
        self.registry = registry
        self.mode = mode
        self.allow_delegation = allow_delegation

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        del command, run_id
        if not self.allow_delegation:
            return (
                ContextSegment(
                    segment_id="agent_delegation_boundary",
                    content=(
                        "<multi_agent_mode>\n"
                        "You are executing a delegated task as a leaf agent. "
                        "Do not create, spawn, or delegate to other agents; "
                        "complete the assigned task directly with your available "
                        "non-delegation tools.\n"
                        "</multi_agent_mode>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-55,
                ),
            )
        if self.mode == AgentMode.SIMPLE:
            return ()
        members = await self.registry.list()
        roster = "\n".join(
            f"- {member.agent_id}: {member.name} — "
            f"{member.description or 'no description'}"
            for member in members
        )
        if not roster:
            roster = "- No existing agents are registered."
        behavior = (
            "Fibre may create a Session-scoped reusable expert with sys_spawn_agent, "
            "then must delegate concrete work with sys_delegate_task using the exact "
            "agent_id returned by spawn or listed below. Independent tasks may be "
            "batched."
            if self.mode == AgentMode.FIBRE
            else "Team has a fixed roster and cannot create agents. Delegate concrete "
            "work with sys_team_delegate_task using exact agent_id values listed below. "
            "Independent tasks may be batched."
        )
        return (
            ContextSegment(
                segment_id="agent_roster",
                content=f"<multi_agent_mode>\n{behavior}\n{roster}\n</multi_agent_mode>",
                stability=ContextStability.SEMI_STABLE,
                priority=-55,
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
        self._binding_closed = False
        self._binding_close_lock = asyncio.Lock()

    async def execute(self, run_id: str, context: RequestContext):
        return await self.loop.execute(run_id, context)

    async def resume(self, run_id: str, context: RequestContext):
        return await self.loop.resume(run_id, context)

    async def close_binding(self) -> None:
        async with self._binding_close_lock:
            if self._binding_closed:
                return
            controller = getattr(self.loop, "delegated_run_controller", None)
            controller_close = getattr(controller, "close", None)
            if controller_close is not None:
                closed = controller_close()
                if inspect.isawaitable(closed):
                    await closed
            await self.sandbox_handle.close()
            self._binding_closed = True


class DesktopV2Service:
    def __init__(
        self,
        root: Path | None = None,
        *,
        catalog: DesktopCatalogStore | None = None,
        log_sink: LogSink | None = None,
        log_plugin_id: str | None = None,
        sidecar_port: int | None = None,
    ) -> None:
        self.root = (root or Path.home() / "sage").resolve()
        self.sidecar_port = sidecar_port
        self.root.mkdir(parents=True, exist_ok=True)
        self.agent_workspace = self.root / "agent_workspace"
        self.runtime_root = self.root / "runtime"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.runtime_root / "settings.json"
        self.extensions = builtin_extension_registry()
        if log_sink is None:
            self._owns_log_sink = True
            self.log_plugin_id, self.log_sink = create_desktop_log_sink(
                self.runtime_root
            )
        else:
            self._owns_log_sink = False
            self.log_plugin_id = log_plugin_id or "injected"
            self.log_sink = log_sink
        self.logger = StructuredLogger(self.log_sink, "desktop.service")
        self.logger.info(
            "service.initializing",
            "Desktop v2 service is initializing",
            attributes={"root": str(self.root), "log_plugin": self.log_plugin_id},
        )
        self.session_plugin_id, self.session_store = self._process_component(
            "session.store",
            {
                "root": str(self.runtime_root),
                "previous_v2_root": str(self.runtime_root / "session-store"),
            },
            allow_user_selection=False,
        )
        self.runtime = HarnessRuntime(self.session_store)
        self.dynamic_agent_roster = SessionDynamicAgentRoster(self.session_store)
        self.summary_store_plugin_id, self.summary_store = self._process_component(
            "context.summary-store",
            {"session_store": self.session_store},
            allow_user_selection=False,
        )
        self.activations = SessionDerivedSkillActivationRepository(
            self.session_store,
            self._session_id_for_run,
        )
        self.diagnostic_plugin_id, self.diagnostics = self._process_component(
            "observability.diagnostic-sink",
            {
                "root": str(self.runtime_root / "sessions"),
                "legacy_root": str(self.runtime_root / "diagnostics"),
            },
            allow_user_selection=False,
        )
        self.memory_plugin_id, self.memory_provider = self._process_component(
            "memory.provider",
            {"root": str(self.runtime_root / "memory")},
            allow_user_selection=True,
        )
        self.memory_service = MemoryService(
            self.memory_provider,
            scope_mode="agent",
            on_error=self._log_memory_error,
        )
        (
            self.session_memory_plugin_id,
            self.session_memory_provider,
        ) = self._process_component(
            "session-memory.provider",
            {"root": str(self.runtime_root / "session-memory")},
            allow_user_selection=True,
        )
        self.session_memory_service = SessionMemoryService(
            self.session_memory_provider, self.session_store
        )
        self.session_index = JsonDesktopSessionIndex(
            self.runtime_root / "session-index.json"
        )
        self.catalog = catalog or JsonDesktopCatalogStore(
            self.runtime_root / "desktop-catalog.json"
        )
        self.skill_root = self.root / "skills"
        self.skill_root.mkdir(parents=True, exist_ok=True)
        self._settings_lock = asyncio.Lock()
        self._drivers: dict[str, _DesktopDriver] = {}
        self._run_observers: dict[str, asyncio.Task] = {}
        self.logger.info(
            "service.initialized",
            "Desktop v2 service initialized",
            attributes={
                "log_path": str(getattr(self.log_sink, "path", "")),
                "diagnostics_path": str(getattr(self.diagnostics, "root", "")),
                "memory_plugin": self.memory_plugin_id,
            },
        )

    def _process_component(
        self,
        capability: str,
        config: dict[str, Any],
        *,
        allow_user_selection: bool,
    ):
        default_plugin_id = _DESKTOP_COMPONENT_DEFAULTS[capability]
        settings = self._read_settings_sync()
        selected = (
            settings.component_selections.get(capability, default_plugin_id)
            if allow_user_selection
            else default_plugin_id
        )
        selected = _stable_component_id(capability, selected)
        try:
            registration = self.extensions.get(selected)
            if capability not in {
                offer.capability for offer in registration.descriptor.provides
            }:
                raise ValueError(
                    f"extension {selected!r} does not provide {capability!r}"
                )
            value = registration.factory(
                ExtensionScopeContext(
                    scope=ExtensionScope.PROCESS,
                    scope_id="desktop-v2",
                    config=config,
                ),
                {},
            )
            if inspect.isawaitable(value):
                raise TypeError(f"{capability} process factory must be synchronous")
            return selected, value
        except Exception as exc:
            if selected == default_plugin_id:
                raise
            self.logger.warning(
                "component.selection_fallback",
                "Configured process component was unavailable; using default",
                attributes={
                    "capability": capability,
                    "selected_plugin": selected,
                    "default_plugin": default_plugin_id,
                    "error": str(exc),
                },
            )
            registration = self.extensions.get(default_plugin_id)
            value = registration.factory(
                ExtensionScopeContext(
                    scope=ExtensionScope.PROCESS,
                    scope_id="desktop-v2",
                    config=config,
                ),
                {},
            )
            if inspect.isawaitable(value):
                raise TypeError(f"{capability} process factory must be synchronous")
            return default_plugin_id, value

    async def _log_memory_error(self, error: Exception) -> None:
        self.logger.exception(
            "memory.ingestion_failed",
            "Committed Run memory ingestion failed",
            error,
        )

    async def initialize_agent_workspace(self) -> Path:
        settings = await self.get_settings()
        return await self._ensure_agent_workspace(
            settings.agent_workspace_path,
            component_selections=settings.component_selections,
            language=settings.language,
        )

    async def close(self) -> None:
        observers = tuple(self._run_observers.values())
        self._run_observers.clear()
        for task in observers:
            task.cancel()
        if observers:
            await asyncio.gather(*observers, return_exceptions=True)
        drivers = tuple(self._drivers.values())
        self._drivers.clear()
        if drivers:
            await asyncio.gather(
                *(driver.close_binding() for driver in drivers),
                return_exceptions=True,
            )
        await self.session_store.close()
        self.logger.info("service.closed", "Desktop v2 service closed")
        if self._owns_log_sink:
            self.log_sink.close()

    async def list_sessions(self) -> list[dict[str, Any]]:
        values = await self.session_index.list()
        return [value.model_dump(mode="json") for value in values]

    async def usage_overview(
        self,
        user_id: str,
        *,
        days: int = 30,
        timezone_offset_minutes: int = 0,
    ) -> dict[str, Any]:
        """Aggregate local Desktop usage without making diagnostics authoritative."""

        if days < 1 or days > 365:
            raise ValueError("days must be between 1 and 365")
        if timezone_offset_minutes < -840 or timezone_offset_minutes > 840:
            raise ValueError("timezone_offset_minutes must be between -840 and 840")

        await self._initialize_user(user_id)
        local_timezone = timezone(timedelta(minutes=timezone_offset_minutes))
        now = utc_now()
        today = now.astimezone(local_timezone).date()
        first_day = today - timedelta(days=days - 1)
        cutoff = datetime.combine(
            first_day, time.min, tzinfo=local_timezone
        ).astimezone(timezone.utc)
        day_keys = [
            (first_day + timedelta(days=offset)).isoformat() for offset in range(days)
        ]
        daily = {
            key: {
                "date": key,
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "turns": 0,
                "tool_calls": 0,
            }
            for key in day_keys
        }
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "model_requests": 0,
            "failed_model_requests": 0,
            "turns": 0,
            "tool_calls": 0,
            "sessions": 0,
        }
        models: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "name": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "requests": 0,
            }
        )
        agents: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "id": "",
                "name": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "requests": 0,
                "turns": 0,
                "tool_calls": 0,
            }
        )
        tools: Counter[str] = Counter()
        active_sessions: set[str] = set()

        agent_records = await self.catalog.list_agents(user_id)
        agent_names = {value.agent_id: value.name for value in agent_records}
        indexed_sessions = await self.session_index.list()

        for session in indexed_sessions:
            session_id = session.session_id
            try:
                runs = await self.session_store.list_session_runs(session_id)
                events = await self.session_store.read_session_events(session_id)
                requests = await self.diagnostics.list_model_requests(
                    session_id=session_id
                )
            except (FileNotFoundError, ValueError):
                continue

            run_agents: dict[str, str] = {}
            for run in runs:
                try:
                    command = await self.session_store.get_start_command(run.run_id)
                    run_agents[run.run_id] = command.agent_id
                except (FileNotFoundError, ValueError):
                    continue

            for record in requests:
                occurred_at = _usage_record_time(record)
                if occurred_at is None or occurred_at < cutoff:
                    continue
                day_key = occurred_at.astimezone(local_timezone).date().isoformat()
                if day_key not in daily:
                    continue
                active_sessions.add(session_id)
                totals["model_requests"] += 1
                if record.get("status") == "failed":
                    totals["failed_model_requests"] += 1

                response = record.get("response")
                usage = response.get("usage") if isinstance(response, dict) else None
                usage = usage if isinstance(usage, dict) else {}
                input_tokens = _safe_nonnegative_int(usage.get("input_tokens"))
                output_tokens = _safe_nonnegative_int(usage.get("output_tokens"))
                cached_tokens = _safe_nonnegative_int(usage.get("cached_input_tokens"))
                reasoning_tokens = _safe_nonnegative_int(usage.get("reasoning_tokens"))
                total_tokens = input_tokens + output_tokens
                values = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cached_input_tokens": cached_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "total_tokens": total_tokens,
                }
                for key, value in values.items():
                    totals[key] += value
                    daily[day_key][key] += value

                # Diagnostics v2 keeps provider/routing details in one compact
                # metadata object. Retain the v1 provider fallback so existing
                # request files continue to contribute to local usage reports.
                metadata = record.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                provider = record.get("provider")
                provider = provider if isinstance(provider, dict) else {}
                request = record.get("request")
                request = request if isinstance(request, dict) else {}
                raw_models = usage.get("models")
                model_name = (
                    str(raw_models[0])
                    if isinstance(raw_models, list) and raw_models
                    else str(
                        request.get("model")
                        or metadata.get("model")
                        or provider.get("model")
                        or request.get("model_binding")
                        or metadata.get("model_binding")
                        or "Unknown"
                    )
                )
                model_value = models[model_name]
                model_value["name"] = model_name
                model_value["requests"] += 1
                for key, value in values.items():
                    model_value[key] += value

                run_id = str(record.get("run_id") or "")
                agent_id = str(
                    metadata.get("agent_id")
                    or provider.get("agent_id")
                    or run_agents.get(run_id)
                    or "unknown"
                )
                agent_value = agents[agent_id]
                agent_value["id"] = agent_id
                agent_value["name"] = agent_names.get(agent_id, agent_id)
                agent_value["requests"] += 1
                for key, value in values.items():
                    agent_value[key] += value

            for event in events:
                if event.occurred_at < cutoff:
                    continue
                day_key = (
                    event.occurred_at.astimezone(local_timezone).date().isoformat()
                )
                if day_key not in daily:
                    continue
                agent_id = run_agents.get(event.run_id, "unknown")
                agent_value = agents[agent_id]
                agent_value["id"] = agent_id
                agent_value["name"] = agent_names.get(agent_id, agent_id)
                if event.type == "turn.started":
                    active_sessions.add(session_id)
                    totals["turns"] += 1
                    daily[day_key]["turns"] += 1
                    agent_value["turns"] += 1
                elif event.type == "tool.call.proposed":
                    active_sessions.add(session_id)
                    totals["tool_calls"] += 1
                    daily[day_key]["tool_calls"] += 1
                    agent_value["tool_calls"] += 1
                    tool_name = str(getattr(event.data, "tool_name", "unknown"))
                    tools[tool_name] += 1

        totals["sessions"] = len(active_sessions)
        return {
            "range_days": days,
            "generated_at": now.isoformat(),
            "totals": totals,
            "daily": list(daily.values()),
            "models": sorted(
                models.values(),
                key=lambda value: (-value["total_tokens"], value["name"]),
            ),
            "agents": sorted(
                agents.values(),
                key=lambda value: (-value["total_tokens"], value["name"]),
            ),
            "tools": [
                {"name": name, "count": count}
                for name, count in sorted(
                    tools.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        }

    async def delete_session(self, session_id: str) -> None:
        deleted_session_ids = {session_id}
        try:
            indexed = await self.session_index.list()
            while True:
                descendants = {
                    value.session_id
                    for value in indexed
                    if value.parent_session_id in deleted_session_ids
                    and value.session_id not in deleted_session_ids
                }
                if not descendants:
                    break
                deleted_session_ids.update(descendants)
        except Exception:
            LOGGER.exception(
                "Desktop Session index lookup failed before deleting %s", session_id
            )
        try:
            await self.session_store.delete_session(session_id)
        except SageV2Error as exc:
            if exc.info.code != "session.not_found":
                raise
            self.logger.info(
                "session.delete.already_absent",
                "Authoritative Session state was already absent; continuing cleanup",
                session_id=session_id,
            )
        try:
            for deleted_session_id in deleted_session_ids:
                await self.session_memory_service.forget_session(deleted_session_id)
        except Exception:
            LOGGER.exception("Derived Session Memory cleanup failed for %s", session_id)
        try:
            await self.session_index.remove_many(deleted_session_ids)
        except Exception:
            LOGGER.exception(
                "Desktop Session tree index removal failed for %s", session_id
            )

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
            "logs": {
                "format_version": self.log_sink.format_version,
                "plugin_id": self.log_plugin_id,
                "path": str(getattr(self.log_sink, "path", "")),
                "authoritative": False,
            },
        }

    async def session_runs(self, session_id: str) -> list[dict[str, Any]]:
        values = await self.session_store.list_session_runs(session_id)
        return [value.model_dump(mode="json") for value in values]

    async def session_tree(self, session_id: str) -> list[dict[str, Any]]:
        """Project the authoritative descendant tree for presentation clients."""

        descendants = await self.session_store.list_descendant_sessions(session_id)
        nodes: list[dict[str, Any]] = []
        for session in descendants:
            runs = await self.session_store.list_session_runs(session.session_id)
            if not runs:
                continue
            run = runs[-1]
            command = await self.session_store.get_start_command(run.run_id)
            metadata = command.config.metadata
            nodes.append(
                {
                    "session": session.model_dump(mode="json"),
                    "run": run.model_dump(mode="json"),
                    "agent_id": command.agent_id,
                    "parent_run_id": command.parent_run_id,
                    "parent_tool_call_id": str(
                        metadata.get("parent_tool_call_id") or ""
                    ),
                    "invocation_mode": command.invocation_mode,
                    "task_name": str(metadata.get("task_name") or ""),
                    "task": _start_run_user_text(command),
                    "original_task": str(
                        metadata.get("original_task") or metadata.get("task") or ""
                    ),
                }
            )
        return nodes

    async def subscribe_session_tree(self, session_id: str) -> AsyncIterator[str]:
        """Multiplex descendant Run logs while preserving their own cursors.

        This is the v2 equivalent of v1's child chunks on the parent stream:
        clients consume one stream, then demultiplex by ``session_id``. Child
        events remain authoritative only in their own Session/Run logs.
        """

        async for observation in self.runtime.subscribe_session_tree(
            session_id, include_root=False
        ):
            command = observation.start_command
            metadata = command.config.metadata
            if observation.kind == "session.discovered":
                value = {
                    "kind": observation.kind,
                    "session": observation.session.model_dump(mode="json"),
                    "run": observation.run.model_dump(mode="json"),
                    "agent_id": command.agent_id,
                    "parent_run_id": command.parent_run_id,
                    "parent_tool_call_id": str(
                        metadata.get("parent_tool_call_id") or ""
                    ),
                    "invocation_mode": command.invocation_mode,
                    "task_name": str(metadata.get("task_name") or ""),
                    "task": _start_run_user_text(command),
                    "original_task": str(
                        metadata.get("original_task") or metadata.get("task") or ""
                    ),
                }
            else:
                value = {
                    "kind": observation.kind,
                    "session_id": observation.session.session_id,
                    "parent_session_id": observation.session.parent_session_id,
                    "run_id": observation.run.run_id,
                    "event": observation.event.model_dump(mode="json"),
                }
            yield json.dumps(value, ensure_ascii=False) + "\n"

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

    async def create_agent(self, request: AgentCreate, user_id: str) -> dict[str, Any]:
        """Create a usable Agent with no inherited configuration or runtime state."""

        await self._initialize_user(user_id)
        name = request.name.strip()
        if not name:
            raise ValueError("agent name cannot be empty")
        providers = await self.catalog.list_model_providers(user_id)
        provider = next((value for value in providers if value.is_default), None)
        provider = provider or (providers[0] if providers else None)
        config = default_agent_config(
            model_provider_id=provider.id if provider is not None else "model_main"
        )
        config["name"] = name
        created = DesktopAgentRecord(
            agent_id=new_id("agent"),
            user_id=user_id,
            name=name,
            config=config,
        )
        await self.catalog.save_agent(created)
        return await self.get_agent_settings(created.agent_id, user_id)

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

    async def list_tools(
        self, user_id: str, language: str | None = None
    ) -> list[dict[str, Any]]:
        categories = {
            **official_tool_categories(),
            "load_skill": "system",
        }
        definitions = []
        for value in self._native_tool_definitions():
            localized = localize_tool_definition(value, language)
            definitions.append(
                {
                    **localized.model_dump(mode="json"),
                    "type": "basic",
                    "category": categories.get(value.name),
                    "source": _tool_category_source(categories.get(value.name)),
                }
            )
        await self._initialize_user(user_id)
        for connection in await self.catalog.list_mcp(user_id):
            if connection.disabled:
                continue
            bridge = McpToolPlugin((self._mcp_config(connection),))
            try:
                discovered = await bridge.list_tools(run_id="desktop-tool-catalog")
            except SageV2Error:
                # One unavailable external server must not hide native tools or
                # prevent another connection from being configured.
                continue
            definitions.extend(
                {
                    **value.model_dump(mode="json"),
                    "type": "mcp",
                    "source": _mcp_source(value.name),
                }
                for value in discovered
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

    def _mcp_config(self, value: DesktopMcpRecord) -> McpServerConfig:
        streamable_url = value.streamable_http_url
        if value.kind == "anytool":
            port = self.sidecar_port or 8080
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
        runtime_variables = config.get("runtimeVariables")
        if runtime_variables is None:
            runtime_variables = config.get("systemContext")
        if runtime_variables is None:
            runtime_variables = config.get("system_context")
        if not isinstance(runtime_variables, dict):
            runtime_variables = {}
        return {
            "id": agent.agent_id,
            "name": agent.name,
            "description": config.get("description") or "",
            "system_prefix": config.get("systemPrefix")
            or config.get("system_prefix")
            or "",
            "runtime_variables": runtime_variables,
            "system_context": runtime_variables,
            "llm_provider_id": config.get("llm_provider_id"),
            "fast_llm_provider_id": config.get("fast_llm_provider_id"),
            "agent_mode": config.get("agentMode")
            or config.get("agent_mode")
            or "simple",
            "sub_agent_selection_mode": config.get("subAgentSelectionMode")
            or config.get("sub_agent_selection_mode")
            or "auto_all",
            "available_sub_agent_ids": list(
                config.get("availableSubAgentIds")
                or config.get("available_sub_agent_ids")
                or []
            ),
            "max_loop_count": int(
                config.get("maxLoopCount") or config.get("max_loop_count") or 100
            ),
            "deep_thinking": deep_thinking,
            "thinking_level": thinking_level,
            "available_tools": list(config.get("availableTools") or []),
            "available_skills": list(config.get("availableSkills") or []),
            "approved_shell_commands": list(config.get("approvedShellCommands") or []),
            "shell_policy": shell_policy_summary(
                config.get("approvedShellCommands") or ()
            ),
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
        updates: dict[str, Any] = {}
        if "name" in fields:
            name = str(patch.name or "").strip()
            if not name:
                raise ValueError("agent name cannot be empty")
            updates["name"] = name
            config["name"] = name
        mapping = {
            "description": "description",
            "system_prefix": "systemPrefix",
            "system_context": "systemContext",
            "runtime_variables": "systemContext",
            "llm_provider_id": "llm_provider_id",
            "fast_llm_provider_id": "fast_llm_provider_id",
            "agent_mode": "agentMode",
            "sub_agent_selection_mode": "subAgentSelectionMode",
            "available_sub_agent_ids": "availableSubAgentIds",
            "max_loop_count": "maxLoopCount",
            "deep_thinking": "deepThinking",
            "thinking_level": "thinkingLevel",
            "available_tools": "availableTools",
            "available_skills": "availableSkills",
            "approved_shell_commands": "approvedShellCommands",
        }
        for field, target in mapping.items():
            if field in fields:
                config[target] = getattr(patch, field)
        if "available_tools" in fields:
            selected_tools = _normalized_assignment_names(
                patch.available_tools, label="tool"
            )
            known = {value["name"] for value in await self.list_tools(user_id)}
            # Keep previously assigned external tools removable even when their
            # MCP server is temporarily unavailable during discovery.
            known.update(agent.config.get("availableTools") or ())
            unknown = set(selected_tools) - known
            if unknown:
                raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
            config["availableTools"] = selected_tools
        if "available_sub_agent_ids" in fields:
            selected_agents = _normalized_assignment_names(
                patch.available_sub_agent_ids, label="sub-agent"
            )
            if agent_id in selected_agents:
                raise ValueError("an agent cannot include itself as a sub-agent")
            known_agents = {
                value.agent_id for value in await self.catalog.list_agents(user_id)
            }
            unknown = set(selected_agents) - known_agents
            if unknown:
                raise ValueError(f"unknown sub-agents: {', '.join(sorted(unknown))}")
            config["availableSubAgentIds"] = selected_agents
        if "available_skills" in fields:
            selected_skills = _normalized_assignment_names(
                patch.available_skills, label="skill"
            )
            known = {value["name"] for value in await self.list_skill_catalog(user_id)}
            known.update(agent.config.get("availableSkills") or ())
            unknown = set(selected_skills) - known
            if unknown:
                raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
            config["availableSkills"] = selected_skills
        if "approved_shell_commands" in fields:
            config["approvedShellCommands"] = sorted(
                {
                    normalized
                    for value in patch.approved_shell_commands or ()
                    if (normalized := normalize_shell_command(value))
                }
            )
        updates.update({"config": config, "updated_at": utc_now()})
        await self.catalog.save_agent(agent.model_copy(update=updates))
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
        settings = await self.get_settings()
        result = []
        process_active = {
            "context.summary-store": self.summary_store_plugin_id,
            "memory.provider": self.memory_plugin_id,
            "session-memory.provider": self.session_memory_plugin_id,
            "observability.diagnostic-sink": self.diagnostic_plugin_id,
            "observability.log-sink": self.log_plugin_id,
            "session.store": self.session_plugin_id,
        }
        for capability, component_spec in _DESKTOP_COMPONENTS.items():
            default_plugin_id = str(component_spec["default"])
            plugins = []
            for registration in self.extensions.registrations():
                descriptor = registration.descriptor
                if capability not in {
                    offer.capability for offer in descriptor.provides
                }:
                    continue
                if (
                    capability == "agent.continuation-policy"
                    and descriptor.plugin_id not in _CONTINUATION_COMPONENT_CHOICES
                ):
                    continue
                plugins.append(
                    {
                        "plugin_id": descriptor.plugin_id,
                        "name": descriptor.name,
                        "value": descriptor.description,
                        "available": descriptor.availability.available,
                        "built_in": descriptor.built_in,
                        "dependencies": [
                            dependency.capability
                            for dependency in descriptor.dependencies
                            if not dependency.optional
                        ],
                        "config_schema": descriptor.config_schema,
                    }
                )
            if capability == "agent.continuation-policy":
                order = {
                    plugin_id: index
                    for index, plugin_id in enumerate(_CONTINUATION_COMPONENT_CHOICES)
                }
                plugins.sort(key=lambda value: order[value["plugin_id"]])
            user_selectable = component_spec["selection_mode"] == "user"
            host_run_config = capability == "execution.sandbox"
            selected = (
                settings.component_selections.get(capability, default_plugin_id)
                if user_selectable or host_run_config
                else default_plugin_id
            )
            selected = _stable_component_id(capability, selected)
            active_plugin_id = process_active.get(capability, selected)
            apply_mode = str(component_spec["apply_mode"])
            result.append(
                {
                    "component": {
                        "component_id": capability,
                        "name": capability,
                        "value": capability,
                        "selection_mode": component_spec["selection_mode"],
                        "apply_mode": apply_mode,
                        "scope": component_spec["scope"],
                    },
                    "plugins": plugins,
                    "active": {
                        "plugin_id": active_plugin_id,
                        "selected_plugin_id": selected,
                        "source": (
                            "user"
                            if user_selectable
                            and capability in settings.component_selections
                            else "host"
                            if host_run_config
                            and capability in settings.component_selections
                            else "default"
                        ),
                        "config": (
                            {
                                "format_version": self.log_sink.format_version,
                                "path": str(getattr(self.log_sink, "path", "")),
                                "min_level": str(
                                    getattr(
                                        getattr(self.log_sink, "min_level", ""),
                                        "value",
                                        getattr(self.log_sink, "min_level", ""),
                                    )
                                ),
                                "max_bytes": getattr(self.log_sink, "max_bytes", None),
                                "backup_count": getattr(
                                    self.log_sink, "backup_count", None
                                ),
                            }
                            if capability == "observability.log-sink"
                            else {
                                "path": str(self.runtime_root / "memory"),
                                "recall": self.memory_plugin_id != "sage.memory.noop",
                                "auto_write": self.memory_plugin_id
                                != "sage.memory.noop",
                                "scope_mode": "agent",
                            }
                            if capability == "memory.provider"
                            else {
                                "path": str(self.runtime_root / "session-memory"),
                                "derived_from": "session.events",
                            }
                            if capability == "session-memory.provider"
                            else {
                                "path": str(getattr(self.diagnostics, "root", "")),
                                "format_version": getattr(
                                    self.diagnostics, "format_version", ""
                                ),
                            }
                            if capability == "observability.diagnostic-sink"
                            else {
                                "path": str(self.runtime_root / "sessions"),
                                "authoritative": True,
                            }
                            if capability == "session.store"
                            else _continuation_component_config(active_plugin_id)
                            if capability == "agent.continuation-policy"
                            else _tool_selection_component_config(
                                selected, settings.component_configs.get(capability)
                            )
                            if capability == "tool.selection-policy"
                            else _resolved_sandbox_config(settings)[1]
                            if capability == "execution.sandbox"
                            else {}
                        ),
                        "pending_restart": (
                            user_selectable
                            and apply_mode == "restart"
                            and selected != active_plugin_id
                        ),
                    },
                }
            )
        return result

    async def select_component(
        self,
        component_id: str,
        request: ComponentSelectionRequest,
        user_id: str,
    ) -> dict[str, Any]:
        del user_id
        component_spec = _DESKTOP_COMPONENTS.get(component_id)
        if component_spec is None or component_spec["selection_mode"] != "user":
            raise ValueError(f"component {component_id!r} is not user configurable")
        if (
            component_id == "agent.continuation-policy"
            and request.plugin_id not in _CONTINUATION_COMPONENT_CHOICES
        ):
            raise ValueError(
                f"completion policy {request.plugin_id!r} is not user selectable"
            )
        registration = self.extensions.get(request.plugin_id)
        capabilities = {offer.capability for offer in registration.descriptor.provides}
        if component_id not in capabilities:
            raise ValueError(
                f"extension {request.plugin_id!r} does not provide {component_id!r}"
            )
        settings = await self.get_settings()
        normalized_config = dict(request.config)
        if component_id == "tool.selection-policy":
            normalized_config = _tool_selection_component_config(
                request.plugin_id, request.config
            )
        choices = dict(settings.component_selections)
        choices[component_id] = request.plugin_id
        configs = dict(settings.component_configs)
        configs[component_id] = normalized_config
        await self.save_settings(
            settings.model_copy(
                update={
                    "component_selections": choices,
                    "component_configs": configs,
                }
            )
        )
        return {
            "component_id": component_id,
            "plugin_id": request.plugin_id,
            "config": normalized_config,
            "pending_restart": (
                component_spec["apply_mode"] == "restart"
                and request.plugin_id
                != {
                    "memory.provider": self.memory_plugin_id,
                    "session-memory.provider": self.session_memory_plugin_id,
                    "observability.log-sink": self.log_plugin_id,
                }.get(component_id, request.plugin_id)
            ),
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
        registration = self.extensions.get(plugin_id)
        initializer = registration.factory(
            ExtensionScopeContext(
                scope=ExtensionScope.AGENT,
                scope_id="desktop-agent-workspace",
                config={"language": language},
            ),
            {},
        )
        if inspect.isawaitable(initializer):
            initializer = await initializer
        initialize = initializer.initialize
        if inspect.iscoroutinefunction(initialize):
            result = initialize(workspace)
        else:
            result = await asyncio.to_thread(initialize, workspace)
        if inspect.isawaitable(result):
            await result
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
        target = self._resolve_child(uploads, safe_name)
        if target.exists():
            raise ValueError(f"upload already exists: {safe_name}")
        await asyncio.to_thread(target.write_bytes, content)
        return {
            "name": safe_name,
            "path": f"uploads/{safe_name}",
            "virtual_path": workspace_root.rstrip("/") + f"/uploads/{safe_name}",
            "size": len(content),
        }

    async def run_events(
        self, request: DesktopRunRequest, user_id: str
    ) -> AsyncIterator[str]:
        accepted_handle = None
        run_logger = self.logger.bind(correlation_id=request.idempotency_key)
        run_logger.info(
            "agent.run.requested",
            "Agent run requested",
            attributes={
                "agent_id": request.agent_id,
                "workspace_id": request.workspace_id,
                "approval_mode": request.approval_mode,
                "invocation_mode": request.invocation_mode,
            },
        )
        try:
            agent = await self._agent(request.agent_id, user_id)
            provider = await self._provider(agent, user_id)
            workspace = await self.workspace_root(
                request.workspace_id, request.agent_id
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
            valid_skills = tuple(
                value
                for value in (agent.config.get("availableSkills") or ())
                if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
            )
            if valid_skills and "load_skill" not in valid_tools:
                valid_tools = (*valid_tools, "load_skill")
            resolved = CompositionResolver().resolve(
                self._manifest(agent, provider, valid_tools, valid_skills)
            )
            command = self._command(request, resolved, agent=agent, workspace=workspace)
            context = self._context(
                user_id,
                language=str(command.config.metadata.get("response_language") or "en"),
            )
            accepted_handle = await self.runtime.start_run(command, context)
            resolved, loop, sandbox_handle = await self._build_loop(
                agent=agent,
                provider=provider,
                workspace=workspace,
                preferred_skills=tuple(request.preferred_skills),
                approval_mode=request.approval_mode,
                invocation_mode=request.invocation_mode,
                session_id=request.session_id,
                run_id=accepted_handle.run_id,
            )
            driver = _DesktopDriver(self, loop, workspace, sandbox_handle)
            memory_enabled = _agent_memory_enabled(
                agent, self.memory_plugin_id, self.session_memory_plugin_id
            )
            facade = SAgent(
                runtime=self.runtime,
                driver_factory=lambda _run_id: driver,
                memory_service=(self.memory_service if memory_enabled else None),
                memory_scope={
                    "recall": memory_enabled,
                    "auto_write": memory_enabled,
                    "scope": "agent",
                    "recall_limit": 8,
                },
            )
            stream = facade.drive_accepted_run(accepted_handle, context)
        except Exception as exc:
            run_logger.exception(
                "agent.run.start_failed",
                "Agent run failed before execution started",
                exc,
                attributes={"agent_id": request.agent_id},
            )
            language = str(
                request.response_language or self._read_settings_sync().language or "en"
            )
            if language == "system":
                language = "zh"
            context = self._context(user_id, language=language)
            fallback = StartRun(
                agent_id=request.agent_id or "desktop_unconfigured_agent",
                input=tuple(
                    InputItem(
                        role=value.role,
                        content=(TextBlock(text=value.text),),
                    )
                    for value in request.messages
                    if value.text.strip()
                ),
                config=RunConfig(metadata={"response_language": language}),
                resolved_spec_hash="sha256:desktop-preflight-v1",
                idempotency_key=(
                    request.idempotency_key or new_id("desktop_preflight_failure")
                ),
            )
            handle = accepted_handle or await self.runtime.start_run(fallback, context)
            failed = await self.runtime.fail_run(
                run_id=handle.run_id,
                expected_revision=(await self.runtime.get_run(handle.run_id)).revision,
                error=RuntimeErrorInfo(
                    code="desktop.run_start_failed",
                    category=(
                        exc.info.category
                        if isinstance(exc, SageV2Error)
                        else ErrorCategory.VALIDATION
                        if isinstance(
                            exc,
                            (ValueError, FileNotFoundError, PermissionError),
                        )
                        else ErrorCategory.INTERNAL
                    ),
                    message=(
                        exc.info.message if isinstance(exc, SageV2Error) else str(exc)
                    ),
                    safe_to_resume=False,
                ),
                context=context,
                idempotency_key=f"desktop-preflight-fail:{handle.run_id}",
            )
            await self._index_session(failed.session_id)
            yield (
                json.dumps(
                    {
                        "kind": "stream.opened",
                        "handle": handle.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            async for event in self.runtime.subscribe_events(
                EventCursor(run_id=handle.run_id, run_sequence=0)
            ):
                yield event.model_dump_json() + "\n"
                if event.type == "run.failed":
                    return
        await self._index_session(stream.handle.session_id)
        self._drivers[stream.handle.run_id] = driver
        self._ensure_run_observer(stream.handle.run_id)
        self.logger.info(
            "agent.run.opened",
            "Agent run stream opened",
            session_id=stream.handle.session_id,
            run_id=stream.handle.run_id,
            attributes={"agent_id": request.agent_id},
        )
        stream._execution.add_done_callback(
            lambda _completed, key=stream.handle.run_id, value=driver: (
                asyncio.create_task(self._discard_driver_if_terminal(key, value))
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
                await self._discard_driver_if_terminal(stream.handle.run_id, driver)
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
            # may be rebuilt or repaired without changing authoritative Session state.
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
            await self._run_context(run_id, user_id),
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
            await self._run_context(run_id, user_id),
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
            await self._run_context(run_id, user_id),
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
            await self._run_context(run_id, user_id),
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
        if decision == "approve_and_remember":
            await self._remember_approved_shell_command(
                run_id=run_id,
                interaction=interaction,
                user_id=user_id,
            )
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
            await self._run_context(run_id, user_id),
        )
        if receipt.decision.value != "rejected":
            await self._continue(run_id, user_id)
        await self._index_session(run.session_id)
        return receipt

    async def _remember_approved_shell_command(
        self,
        *,
        run_id: str,
        interaction,
        user_id: str,
    ) -> str:
        if "approve_and_remember" not in interaction.allowed_decisions:
            raise ValueError("this approval cannot be remembered")
        payload = interaction.payload
        if payload.get("tool_name") != "execute_shell_command":
            raise ValueError("only shell command approvals can be remembered")
        arguments = payload.get("arguments")
        command_value = (
            arguments.get("command") if isinstance(arguments, dict) else None
        )
        command = normalize_shell_command(command_value)
        if not command:
            raise ValueError("shell approval has no command to remember")

        start_command = await self.session_store.get_start_command(run_id)
        agent = await self._agent(start_command.agent_id, user_id)
        config = dict(agent.config or {})
        remembered = {
            normalized
            for value in config.get("approvedShellCommands") or ()
            if (normalized := normalize_shell_command(value))
        }
        remembered.add(command)
        config["approvedShellCommands"] = sorted(remembered)
        await self.catalog.save_agent(
            agent.model_copy(update={"config": config, "updated_at": utc_now()})
        )

        driver = self._drivers.get(run_id)
        assessor = (
            getattr(driver.loop.tool_policy, "operation_assessor", None)
            if driver is not None
            else None
        )
        if isinstance(assessor, ShellCommandOperationAssessor):
            assessor.approve_command(command)
        return command

    async def _continue(self, run_id: str, user_id: str) -> None:
        self._ensure_run_observer(run_id)
        command = await self.session_store.get_start_command(run_id)
        agent = await self._agent(command.agent_id, user_id)
        memory_enabled = _agent_memory_enabled(
            agent, self.memory_plugin_id, self.session_memory_plugin_id
        )
        driver = self._drivers.get(run_id)
        if driver is None:
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
                invocation_mode=command.invocation_mode or "normal",
                session_id=(await self.runtime.get_run(run_id)).session_id,
                run_id=run_id,
            )
            driver = _DesktopDriver(self, loop, workspace, sandbox_handle)
            self._drivers[run_id] = driver
        facade = SAgent(
            runtime=self.runtime,
            driver_factory=lambda _: driver,
            memory_service=(self.memory_service if memory_enabled else None),
            memory_scope={
                "recall": memory_enabled,
                "auto_write": memory_enabled,
                "scope": "agent",
                "recall_limit": 8,
            },
        )
        task = await facade.continue_run(
            run_id,
            self._context(
                user_id,
                language=str(command.config.metadata.get("response_language") or "en"),
            ),
        )
        task.add_done_callback(
            lambda _completed, key=run_id, value=driver: asyncio.create_task(
                self._discard_driver_if_terminal(key, value)
            )
        )
        task.add_done_callback(
            lambda _completed, key=run_id: asyncio.create_task(self._index_run(key))
        )

    def _discard_driver(self, run_id: str, driver: _DesktopDriver) -> None:
        if self._drivers.get(run_id) is driver:
            self._drivers.pop(run_id, None)

    async def _discard_driver_if_terminal(
        self, run_id: str, driver: _DesktopDriver
    ) -> None:
        try:
            run = await self.runtime.get_run(run_id)
        except Exception:
            return
        if run.state in TERMINAL_RUN_STATES:
            await driver.close_binding()
            self._discard_driver(run_id, driver)

    def _ensure_run_observer(self, run_id: str) -> None:
        current = self._run_observers.get(run_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(
            self._observe_run(run_id),
            name=f"desktop-log-observer:{run_id}",
        )
        self._run_observers[run_id] = task
        task.add_done_callback(
            lambda completed, key=run_id: (
                self._run_observers.pop(key, None)
                if self._run_observers.get(key) is completed
                else None
            )
        )

    async def _observe_run(self, run_id: str) -> None:
        try:
            async for event in self.runtime.subscribe_events(
                EventCursor(run_id=run_id, run_sequence=0)
            ):
                self._write_runtime_event(event)
                if event.type in {
                    "run.completed",
                    "run.failed",
                    "run.cancelled",
                }:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception(
                "agent.run.observer_failed",
                "Agent run log observer failed",
                exc,
                run_id=run_id,
            )

    def _write_runtime_event(self, event) -> None:
        if event.data.kind in {"item", "usage", "protocol"}:
            return
        data = event.data.model_dump(mode="json", exclude_none=True)
        data.pop("arguments", None)
        runtime_error = data.pop("error", None)
        level = (
            LogLevel.ERROR
            if event.type.endswith(".failed") or runtime_error is not None
            else LogLevel.WARNING
            if event.type.endswith(".unknown")
            or event.type.endswith(".cancelled")
            or event.type.endswith(".rejected")
            else LogLevel.INFO
        )
        tool_call_id = data.get("tool_call_id")
        self.log_sink.write(
            LogRecord(
                level=level,
                event=event.type,
                message=f"Runtime event {event.type}",
                component=f"agent.{event.source.source_type.value}",
                process_id=os.getpid(),
                session_id=event.session_id,
                run_id=event.run_id,
                turn_id=event.turn_id,
                step_id=event.step_id,
                tool_call_id=(str(tool_call_id) if tool_call_id is not None else None),
                correlation_id=event.correlation_id,
                error=(
                    LogError(
                        type="RuntimeErrorInfo",
                        message=str(runtime_error.get("message") or "Runtime failure"),
                        code=runtime_error.get("code"),
                        category=runtime_error.get("category"),
                    )
                    if isinstance(runtime_error, dict)
                    else None
                ),
                attributes={
                    "event_id": event.event_id,
                    "run_sequence": event.run_sequence,
                    "session_sequence": event.session_sequence,
                    "durability": event.durability.value,
                    "source_id": event.source.source_id,
                    "data": data,
                },
            )
        )

    async def _build_loop(
        self,
        *,
        agent,
        provider,
        workspace,
        preferred_skills,
        approval_mode,
        invocation_mode="normal",
        session_id: str | None = None,
        run_id: str | None = None,
        force_leaf: bool = False,
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
        tool_definitions = (*self._native_tool_definitions(), *mcp_definitions)
        known_tools = {value.name for value in tool_definitions}
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
            "context.token-estimator",
            _DESKTOP_COMPONENT_DEFAULTS["context.token-estimator"],
        )
        reducer_id = settings.component_selections.get(
            "context.reducer", _DESKTOP_COMPONENT_DEFAULTS["context.reducer"]
        )
        estimator_id = _runtime_component_id(
            "context.token-estimator",
            _stable_component_id("context.token-estimator", estimator_id),
        )
        reducer_id = _runtime_component_id(
            "context.reducer",
            _stable_component_id("context.reducer", reducer_id),
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
                "agent_id": agent.agent_id,
                "provider_id": provider.id,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
            },
        )
        judge_provider = await self._fast_provider(agent, provider)
        judge_recording_model = RecordingModelProvider(
            self._model_provider(judge_provider, agent, enable_thinking=False),
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": judge_provider.id,
                "protocol": judge_provider.protocol,
                "base_url": judge_provider.base_url,
                "model": judge_provider.model,
                "purpose": "task_complete_judge",
                "model_type": "fast",
            },
        )
        memory_query_plugin_id = _stable_component_id(
            "memory.recall-query",
            settings.component_selections.get(
                "memory.recall-query",
                _DESKTOP_COMPONENT_DEFAULTS["memory.recall-query"],
            ),
        )
        memory_query_model = RecordingModelProvider(
            self._model_provider(judge_provider, agent, enable_thinking=False),
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": judge_provider.id,
                "protocol": judge_provider.protocol,
                "base_url": judge_provider.base_url,
                "model": judge_provider.model,
                "purpose": "memory_recall_query",
                "model_type": "fast",
            },
        )
        tool_selection_model = RecordingModelProvider(
            self._model_provider(judge_provider, agent, enable_thinking=False),
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": judge_provider.id,
                "protocol": judge_provider.protocol,
                "base_url": judge_provider.base_url,
                "model": judge_provider.model,
                "purpose": "tool_selection",
                "model_type": "fast",
            },
        )
        memory_query_generator = self._component_instance(
            "memory.recall-query",
            memory_query_plugin_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-memory-query:{agent.agent_id}",
            agent_id=agent.agent_id,
            config=(
                {"model": memory_query_model, "language": settings.language}
                if memory_query_plugin_id == "sage.memory.recall-query.llm"
                else {}
            ),
        )
        summarizer_plugin_id = _stable_component_id(
            "context.summarizer",
            settings.component_selections.get(
                "context.summarizer",
                _DESKTOP_COMPONENT_DEFAULTS["context.summarizer"],
            ),
        )
        summarizer = self._component_instance(
            "context.summarizer",
            summarizer_plugin_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-summarizer:{agent.agent_id}",
            agent_id=agent.agent_id,
            config={"model": recording_model, "model_binding": "summary"},
        )
        continuation_plugin_id = _stable_component_id(
            "agent.continuation-policy",
            settings.component_selections.get(
                "agent.continuation-policy",
                _DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"],
            ),
        )
        factory = AgentCompositionFactory(
            self.runtime,
            context_components=ContextComponentBundle(
                token_estimator=TokenEstimatorRegistry().create(estimator_id),
                summary_store=self.summary_store,
                summarizer=summarizer,
                reducer_id=reducer_id,
            ),
        )
        await self._ensure_agent_workspace(
            settings.agent_workspace_path,
            component_selections=settings.component_selections,
            language=settings.language,
        )
        sandbox_plugin_id, sandbox_config = _resolved_sandbox_config(settings)
        workspace_root = _sandbox_workspace_root(sandbox_config, workspace)
        issuer = SandboxGrantIssuer()
        sandbox_provider = self._component_instance(
            "execution.sandbox",
            sandbox_plugin_id,
            scope=ExtensionScope.RUN,
            scope_id=f"desktop-sandbox:{agent.agent_id}",
            agent_id=agent.agent_id,
            config={"verification_key": issuer.verification_key},
        )
        capabilities = await sandbox_provider.capabilities()
        architecture = str(
            sandbox_config.get("architecture") or capabilities.architectures[0]
        )
        filesystem_mode = FileSystemMode(str(sandbox_config["filesystem_mode"]))
        if architecture not in capabilities.architectures:
            raise ValueError("sandbox architecture is unsupported by the provider")
        if filesystem_mode not in capabilities.filesystem_modes:
            raise ValueError("sandbox filesystem_mode is unsupported by the provider")
        process_enabled = bool(
            sandbox_config.get("process_enabled", capabilities.process.available)
        )
        if process_enabled and not capabilities.process.available:
            raise ValueError("sandbox process execution is unsupported by the provider")
        fingerprint_source = json.dumps(
            {
                "plugin_id": sandbox_plugin_id,
                "config": sandbox_config,
                "host_workspace": str(workspace)
                if sandbox_config["workspace_mapping"] == "active_workspace"
                else None,
                "invocation_mode": invocation_mode,
            },
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
        sandbox_metadata: dict[str, Any] = {}
        if sandbox_config["workspace_mapping"] == "active_workspace":
            sandbox_metadata["host_workspace"] = str(workspace)
        sandbox_handle = await sandbox_provider.provision(
            ResolvedSandboxSpec(
                spec_hash=f"sha256:{fingerprint}",
                workspace_root=workspace_root,
                architecture=architecture,
                filesystem_mode=filesystem_mode,
                filesystem=FileSystemPolicy(
                    allowed_operations=(
                        frozenset({FileOperation.READ, FileOperation.LIST})
                        if invocation_mode == "plan"
                        else frozenset(FileOperation)
                    ),
                    allowed_roots=(workspace_root,),
                    max_file_bytes=64 * 1024 * 1024,
                    max_total_bytes=4 * 1024 * 1024 * 1024,
                ),
                process=ProcessPolicy(
                    enabled=process_enabled,
                    read_only=invocation_mode == "plan",
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
                metadata=sandbox_metadata,
            ),
            self._context(agent.user_id, language=settings.language),
            run_id=run_id or new_id("desktop_sandbox"),
        )
        skill_workspace = (
            LocalSkillWorkspace(workspace, workspace_root=workspace_root)
            if sandbox_config["workspace_mapping"] == "active_workspace"
            else SandboxSkillWorkspace(sandbox_handle, issuer)
        )
        loader = factory.create_skill_loader(
            resolved,
            agent.agent_id,
            catalog=skill_provider,
            source=skill_provider,
            workspace=skill_workspace,
            activations=self.activations,
            workspace_root=workspace_root,
        )
        goal_state_service = GoalStateService(self.session_store)
        raw_tool_selection = agent.config.get("toolSelection")
        legacy_tool_selection_config = (
            dict(raw_tool_selection) if isinstance(raw_tool_selection, dict) else {}
        )
        legacy_plugin_id = str(
            legacy_tool_selection_config.pop(
                "plugin", _DESKTOP_COMPONENT_DEFAULTS["tool.selection-policy"]
            )
        )
        tool_selection_plugin_id = _stable_component_id(
            "tool.selection-policy",
            settings.component_selections.get(
                "tool.selection-policy", legacy_plugin_id
            ),
        )
        configured_tool_selection = settings.component_configs.get(
            "tool.selection-policy"
        )
        tool_selection_config = _tool_selection_component_config(
            tool_selection_plugin_id,
            configured_tool_selection
            if configured_tool_selection is not None
            else legacy_tool_selection_config,
        )
        tool_selection_policy = self._component_instance(
            "tool.selection-policy",
            tool_selection_plugin_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-tool-selection:{agent.agent_id}",
            agent_id=agent.agent_id,
            config=tool_selection_config,
        )
        official_runtime = OfficialToolRuntime(
            sandbox_handle,
            issuer,
            memory_service=self.memory_service,
            session_memory_service=self.session_memory_service,
            goal_state_service=goal_state_service,
            tool_selection_policy=tool_selection_policy,
        )
        official_tools = self._official_tools(official_runtime)
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
        mode = AgentMode(str(agent.config.get("agentMode") or "simple").strip().lower())
        root_descriptor = AgentDescriptor(
            agent_id=agent.agent_id,
            name=agent.name,
            description=str(agent.config.get("description") or ""),
            instructions=(
                agent.config.get("systemPrefix") or "You are a helpful Sage agent."
            ),
            mode=mode,
            tools=tuple(
                value
                for value in valid_tools
                if not (
                    continuation_plugin_id == "sage.agent.continuation.llm-judge"
                    and value == "turn_status"
                )
            ),
            skills=tuple(valid_skills),
            allow_delegation=not force_leaf,
        )
        member_descriptors: list[AgentDescriptor] = []
        models_by_agent = {agent.agent_id: recording_model}
        judge_models_by_agent = {agent.agent_id: judge_recording_model}
        configured_member_ids = {
            str(value)
            for value in (agent.config.get("availableSubAgentIds") or ())
            if str(value)
        }
        manual_member_roster = (
            mode in {AgentMode.FIBRE, AgentMode.TEAM}
            and str(agent.config.get("subAgentSelectionMode") or "auto_all") == "manual"
        )
        catalog_members = await self.catalog.list_agents(agent.user_id)
        members_by_id = {value.agent_id: value for value in catalog_members}
        for member in catalog_members:
            if member.agent_id == agent.agent_id:
                continue
            if manual_member_roster and member.agent_id not in configured_member_ids:
                continue
            member_tools = tuple(
                value
                for value in (member.config.get("availableTools") or ())
                if isinstance(value, str)
                and value in known_tools
                and not (
                    continuation_plugin_id == "sage.agent.continuation.llm-judge"
                    and value == "turn_status"
                )
            )
            member_skills = tuple(
                value
                for value in (member.config.get("availableSkills") or ())
                if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
            )
            member_mode = AgentMode(
                str(member.config.get("agentMode") or "simple").strip().lower()
            )
            member_descriptors.append(
                AgentDescriptor(
                    agent_id=member.agent_id,
                    name=member.name,
                    description=str(member.config.get("description") or ""),
                    instructions=(
                        member.config.get("systemPrefix")
                        or "You are a helpful Sage agent."
                    ),
                    mode=member_mode,
                    tools=member_tools,
                    skills=member_skills,
                    allow_delegation=False,
                )
            )
            member_provider = await self._provider(member, member.user_id)
            models_by_agent[member.agent_id] = RecordingModelProvider(
                self._model_provider(member_provider, member),
                sink=self.diagnostics,
                session_id_resolver=self._session_id_for_run,
                provider_metadata={
                    "agent_id": member.agent_id,
                    "provider_id": member_provider.id,
                    "protocol": member_provider.protocol,
                    "base_url": member_provider.base_url,
                    "model": member_provider.model,
                },
            )
            member_judge_provider = await self._fast_provider(member, member_provider)
            judge_models_by_agent[member.agent_id] = RecordingModelProvider(
                self._model_provider(
                    member_judge_provider, member, enable_thinking=False
                ),
                sink=self.diagnostics,
                session_id_resolver=self._session_id_for_run,
                provider_metadata={
                    "agent_id": member.agent_id,
                    "provider_id": member_judge_provider.id,
                    "protocol": member_judge_provider.protocol,
                    "base_url": member_judge_provider.base_url,
                    "model": member_judge_provider.model,
                    "purpose": "task_complete_judge",
                    "model_type": "fast",
                },
            )

        resolved_agent = resolved.agents[agent.agent_id]
        route_id = resolved_agent.model_bindings.get("primary")
        route = resolved.model_routes.get(route_id, {})
        limits = route.get("limits", {})
        request_defaults = route.get("request", {})
        ceiling = resolved.policy_ceilings[agent.agent_id]
        context_limits = [
            value
            for value in (
                limits.get("context_window"),
                ceiling.max_input_tokens,
            )
            if value is not None
        ]
        context_budget = (
            ContextBudget(
                max_input_tokens=min(int(value) for value in context_limits),
                reserve_output_tokens=int(
                    request_defaults.get("max_output_tokens")
                    or limits.get("max_output_tokens")
                    or ceiling.max_output_tokens
                    or 0
                ),
            )
            if context_limits
            else None
        )

        if mode == AgentMode.FIBRE and session_id:
            try:
                dynamic_members = await self.dynamic_agent_roster.load(session_id)
            except SageV2Error as exc:
                if exc.info.code != "session.not_found":
                    raise
                # Desktop allocates a stable Session ID before the first Run so
                # attachments and UI state can already be scoped to it. The
                # authoritative Session is created by start_run after loop
                # composition, therefore a brand-new Fibre has no durable
                # dynamic roster to restore yet.
                dynamic_members = ()
            existing_ids = {value.agent_id for value in member_descriptors}
            member_descriptors.extend(
                value for value in dynamic_members if value.agent_id not in existing_ids
            )

        member_registry = AgentRegistry(tuple(member_descriptors))

        def compose_mode_loop(descriptor, run_id, catalog, executor):
            context_providers = (
                RunMetadataContextProvider(),
                PlanContextProvider(goal_state_service),
                GoalContextProvider(goal_state_service),
                AgentRosterContextProvider(
                    member_registry,
                    descriptor.mode,
                    allow_delegation=descriptor.allow_delegation,
                ),
                AvailableSkillsContextProvider(loader.catalog),
                ActiveSkillsContextProvider(loader),
                PreferredSkillsContextProvider(),
            )
            base_continuation_policy = self._component_instance(
                "agent.continuation-policy",
                continuation_plugin_id,
                scope=ExtensionScope.AGENT,
                scope_id=f"desktop-continuation:{descriptor.agent_id}:{run_id}",
                agent_id=descriptor.agent_id,
                config={
                    "repeat_threshold": 3,
                    "model": judge_models_by_agent.get(
                        descriptor.agent_id, judge_recording_model
                    ),
                    "model_binding": "fast",
                },
            )
            continuation_policy = base_continuation_policy
            owns_invocation = descriptor.agent_id == agent.agent_id
            if invocation_mode == "plan" and owns_invocation:
                continuation_policy = PlanCompletionGatePolicy(
                    continuation_policy,
                    goal_state_service,
                )
            elif invocation_mode == "goal" and owns_invocation:
                continuation_policy = GoalCompletionGatePolicy(
                    continuation_policy,
                    goal_state_service,
                )
            return AgentLoopEngine(
                runtime=self.runtime,
                model=models_by_agent.get(descriptor.agent_id, recording_model),
                tool_catalog=catalog,
                tool_executor=executor,
                tool_policy=DefaultToolPolicy(
                    approval_strategy=ApprovalStrategy(approval_mode),
                    operation_assessor=ShellCommandOperationAssessor(
                        agent.config.get("commandPolicy"),
                        agent.config.get("approvedShellCommands") or (),
                    ),
                    operation_assessor_id="v2-desktop-shell-policy",
                ),
                tool_selection_policy=tool_selection_policy,
                tool_selection_model=tool_selection_model,
                continuation_policy=continuation_policy,
                continuation_signal_provider=(
                    official_runtime.consume_continuation_signals
                ),
                automatic_memory_recall=(
                    (
                        self.memory_plugin_id != "sage.memory.noop"
                        or self.session_memory_plugin_id != "sage.session-memory.noop"
                    )
                    and "search_memory" in descriptor.tools
                ),
                memory_recall_limit=8,
                memory_recall_query_generator=memory_query_generator,
                context_assembler=DefaultContextAssembler(
                    developer_instructions=(
                        descriptor.instructions
                        + _continuation_agent_instructions(continuation_plugin_id)
                    ),
                    providers=context_providers,
                    budget=context_budget,
                    reducer=(
                        factory.context_components.create_reducer()
                        if context_budget is not None
                        else None
                    ),
                    estimator=factory.context_components.token_estimator,
                    history_reader=self.runtime.session_store,
                    projection_observer=self.session_memory_service,
                ),
            )

        async def compose_child_loop(descriptor, child_run_id, child_context):
            del child_context
            member = members_by_id.get(descriptor.agent_id)
            if member is None:
                member_config = {
                    **agent.config,
                    "description": descriptor.description,
                    "systemPrefix": descriptor.instructions,
                    "agentMode": descriptor.mode.value,
                    "availableTools": list(descriptor.tools),
                    "availableSkills": list(descriptor.skills),
                }
                member = agent.model_copy(
                    update={
                        "agent_id": descriptor.agent_id,
                        "name": descriptor.name,
                        "config": member_config,
                    }
                )
            member_provider = await self._provider(member, member.user_id)
            child_run = await self.runtime.get_run(child_run_id)
            _, child_loop, child_sandbox = await self._build_loop(
                agent=member,
                provider=member_provider,
                workspace=workspace,
                preferred_skills=(),
                approval_mode=approval_mode,
                invocation_mode="normal",
                session_id=child_run.session_id,
                run_id=child_run_id,
                force_leaf=descriptor.mode != AgentMode.TEAM,
            )
            return child_loop, child_sandbox

        mode_factory = ModeAwareAgentLoopFactory(
            runtime=self.runtime,
            model_factory=lambda descriptor, run_id: models_by_agent.get(
                descriptor.agent_id, recording_model
            ),
            base_catalog=native_catalog,
            base_executor=native_executor,
            registry=member_registry,
            resolved_spec_hash=resolved.manifest_hash,
            max_delegation_concurrency=4,
            loop_composer=compose_mode_loop,
            workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
            fallback_invocation_mode=invocation_mode,
            child_loop_factory=compose_child_loop,
        )
        loop = mode_factory.create_loop(root_descriptor, run_id or "pending")
        return resolved, loop, sandbox_handle

    def _component_instance(
        self,
        capability: str,
        plugin_id: str,
        *,
        scope: ExtensionScope,
        scope_id: str,
        config: dict[str, Any],
        agent_id: str | None = None,
        run_id: str | None = None,
    ):
        registration = self.extensions.get(plugin_id)
        if capability not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(f"extension {plugin_id!r} does not provide {capability!r}")
        value = registration.factory(
            ExtensionScopeContext(
                scope=scope,
                scope_id=scope_id,
                agent_id=agent_id,
                run_id=run_id,
                config=config,
            ),
            {},
        )
        if inspect.isawaitable(value):
            raise TypeError(f"{capability} factory must be synchronous")
        return value

    async def _session_id_for_run(self, run_id: str) -> str:
        return (await self.session_store.get_run(run_id)).session_id

    def _manifest(self, agent, provider, tools, skills):
        max_steps = max(1, min(int(agent.config.get("maxLoopCount") or 24), 200))
        deep_thinking, thinking_level = self._thinking_config(agent)
        memory_enabled = (
            self.memory_plugin_id != "sage.memory.noop" and "search_memory" in tools
        )
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
                    memory=AgentMemoryBehavior(
                        recall=memory_enabled,
                        auto_write=memory_enabled,
                        scope="agent",
                    ),
                )
            },
            entrypoint=ApplicationEntrypoint(agent=agent.agent_id),
        )

    def _model_provider(self, provider, agent, *, enable_thinking: bool | None = None):
        model_lower = provider.model.lower()
        max_field = (
            "max_completion_tokens"
            if model_lower.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        deep_thinking, thinking_level = self._thinking_config(agent)
        if enable_thinking is not None:
            deep_thinking = enable_thinking
        reasoning_effort = thinking_level if deep_thinking else None
        request_extra: dict[str, Any] = {}
        if provider.protocol == "openai-chat-completions":
            request_extra["max_output_tokens_field"] = max_field
            if enable_thinking is not None:
                # V1 sent explicit provider-compatible thinking controls. Merely
                # omitting reasoning_effort does not disable thinking on many
                # OpenAI-compatible endpoints, so preserve that behavior here.
                request_extra.update(
                    build_llm_extra_body(
                        provider.model,
                        base_url=provider.base_url,
                        enable_thinking=enable_thinking,
                        thinking_level=(thinking_level if enable_thinking else None),
                        default_off="minimal",
                    )
                )
        elif provider.protocol == "openai-responses" and enable_thinking is False:
            # OpenAI reasoning models do not expose a disabled state; minimal is
            # the smallest supported effort for auxiliary Judge requests.
            reasoning_effort = "minimal"
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=provider.max_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=request_extra,
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

    async def _fast_provider(
        self,
        agent: DesktopAgentRecord,
        fallback: DesktopModelProviderRecord,
    ) -> DesktopModelProviderRecord:
        provider_id = str(agent.config.get("fast_llm_provider_id") or "").strip()
        if not provider_id:
            return fallback
        provider = await self.catalog.get_model_provider(provider_id, agent.user_id)
        if provider is None or not provider.api_key or not provider.base_url:
            return fallback
        return provider

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
        settings = self._read_settings_sync()
        _, sandbox_config = _resolved_sandbox_config(settings)
        workspace_root = _sandbox_workspace_root(
            sandbox_config,
            Path(workspace) if workspace is not None else None,
        )
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
        configured_response_language = configured_context.pop("response_language", None)
        response_language = str(
            request.response_language
            or configured_response_language
            or settings.language
            or "en"
        )
        if response_language == "system":
            response_language = "zh"
        response_language = normalize_language(response_language)
        metadata = {
            "workspace_id": request.workspace_id,
            "preferred_skills": request.preferred_skills,
            "approval_mode": request.approval_mode,
            "invocation_mode": request.invocation_mode,
            "response_language": response_language,
            "system_context": configured_context,
            "current_time": current_time,
            "identity_documents": self._identity_documents(
                self._agent_workspace_path(settings.agent_workspace_path)
            ),
        }
        if workspace is not None:
            metadata["working_directory"] = workspace_root
            metadata["workspace_files"] = self._workspace_prompt_listing(
                Path(workspace).resolve()
                if sandbox_config["workspace_mapping"] == "active_workspace"
                else None,
                workspace_root=workspace_root,
            )
        for key in ("todo", "external_paths", "shell_completion_reminder"):
            if key in configured_context:
                metadata[key] = configured_context.pop(key)
        run_config = CompositionResolver().resolve_run_config(
            resolved,
            request.agent_id,
            metadata=metadata,
        )
        invocation_grants = {
            "plan": ("goal_submit",),
            "goal": ("goal_submit", "goal_complete"),
        }.get(request.invocation_mode, ())
        if invocation_grants:
            enabled_tools = (
                *run_config.enabled_tools,
                *(
                    name
                    for name in invocation_grants
                    if name not in run_config.enabled_tools
                ),
            )
            run_config = run_config.model_copy(
                update={
                    "enabled_tools": enabled_tools,
                    "metadata": {
                        **run_config.metadata,
                        "enabled_tools": list(enabled_tools),
                    },
                }
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
            invocation_mode=request.invocation_mode,
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
    def _workspace_prompt_listing(
        root: Path | None, *, workspace_root: str = "/workspace", maximum: int = 200
    ) -> str:
        """Freeze a deterministic, bounded two-level workspace view for one Run."""

        if root is None:
            return f"Working directory: {workspace_root}\n(Empty isolated sandbox)"
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
            f"Working directory: {workspace_root}"
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
        command = await self.session_store.get_start_command(run_id)
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


def _usage_record_time(record: dict[str, Any]) -> datetime | None:
    raw = record.get("completed_at") or record.get("started_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _start_run_user_text(command: StartRun) -> str:
    values: list[str] = []
    for item in command.input:
        if item.role != "user":
            continue
        for block in item.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                values.append(text.strip())
    return "\n".join(values)


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
