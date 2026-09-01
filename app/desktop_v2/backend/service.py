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
from contextvars import ContextVar
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from sagents.llm.model_capabilities import (
    build_llm_extra_body,
    is_openai_reasoning_model,
)
from app.desktop_v2.backend.catalog import (
    DesktopAgentRecord,
    DesktopCatalogStore,
    DesktopMcpRecord,
    DesktopModelCompatibilityProfile,
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
from sagents.v2 import (
    ResolvedApplicationPlan,
    ResolvedProviderBinding,
    SAgent,
    SAgentApplication,
)
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    DelegationConcurrencyLimiter,
    SessionDynamicAgentRoster,
    WorkspaceSharingPolicy,
)
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
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
    RunState,
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
from sagents.v2.runtime.execution import LocalWorkerDispatcher
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.session import AuthorizedSessionAccess, LeaseFencedSessionStore
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
    probe_model_capabilities,
    probe_model_connection,
    probe_model_json_object,
    probe_model_tool_calling,
    resolve_model_protocol,
)
from sagents.v2.model.protocols import create_registered_model_provider
from sagents.v2.model.plugins.openai_compatible import (
    default_chat_completion_token_field,
)
from sagents.v2.runtime.extensions import (
    CapabilityRequirement,
    ExtensionHost,
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.agent.policy import (
    ApprovalStrategy,
    DefaultToolPolicy,
)
from sagents.v2.runtime.execution.sandbox import (
    FileSystemMode,
    FileOperation,
    FileSystemPolicy,
    IsolationLevel,
    LifecyclePolicy,
    NetworkPolicy,
    OperationIntent,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxGrantIssuer,
    SandboxHandle,
    SandboxReleaseDisposition,
)
from sagents.v2.runtime.execution import (
    ExecutionBindingLifecycleCoordinator,
    ExecutionResourceState,
)
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
    FilesystemSkillProvider,
    SessionDerivedSkillActivationRepository,
    SkillLoadTool,
)
from sagents.v2.tool import decorated_tool_definition
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability import (
    LogError,
    LogLevel,
    LogRecord,
    LogSink,
    StructuredLogger,
)
from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor
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
_PLAN_BLOCKED_TOOLS = frozenset(
    {
        "apply_patch",
        "await_shell",
        "execute_shell_command",
        "file_update",
        "file_write",
        "kill_shell",
    }
)
LOGGER = logging.getLogger(__name__)

_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
_OUTPUT_TOKEN_FALLBACKS = (
    65_536,
    32_768,
    16_384,
    8_192,
    4_096,
    2_048,
    1_024,
    512,
    256,
    128,
)
_REASONING_DISABLE_EXTRAS: dict[str, dict[str, Any]] = {
    "omit": {},
    "reasoning_effort_none": {"reasoning_effort": "none"},
    "thinking_type_disabled": {"thinking": {"type": "disabled"}},
    "enable_thinking_false": {"enable_thinking": False},
    "thinking_false": {"thinking": False},
    "chat_template_enable_thinking_false": {
        "chat_template_kwargs": {"enable_thinking": False}
    },
}
_ACTIVE_EXTENSION_SCOPE_HANDLES: ContextVar[list[Any] | None] = ContextVar(
    "desktop_v2_active_extension_scope_handles", default=None
)
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


def _desktop_component_scope(capability: str) -> str:
    return str(_DESKTOP_COMPONENTS.get(capability, {}).get("scope", "process"))


def _desktop_component_api_version(capability: str) -> str:
    return "3" if capability == "execution.sandbox" else "2"


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
            "judge_failure": "deterministic_fallback_on_permanent_error",
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


def _component_cache_fingerprint(value: Any) -> str:
    """Create a deterministic, secret-safe identity for long-lived components."""

    def normalize(candidate: Any, seen: set[int]) -> Any:
        if candidate is None or isinstance(candidate, (str, int, float, bool)):
            return candidate
        if isinstance(candidate, SecretStr):
            secret = candidate.get_secret_value().encode()
            return {"secret_sha256": hashlib.sha256(secret).hexdigest()}
        if isinstance(candidate, bytes):
            return {"bytes_sha256": hashlib.sha256(candidate).hexdigest()}
        if isinstance(candidate, Path):
            return str(candidate)
        if isinstance(candidate, BaseModel):
            return normalize(candidate.model_dump(mode="python"), seen)
        if isinstance(candidate, dict):
            return {
                str(key): normalize(item, seen)
                for key, item in sorted(
                    candidate.items(), key=lambda pair: str(pair[0])
                )
            }
        if isinstance(candidate, (list, tuple)):
            return [normalize(item, seen) for item in candidate]
        if isinstance(candidate, (set, frozenset)):
            return sorted(
                (normalize(item, seen) for item in candidate),
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
        identity = id(candidate)
        type_name = f"{type(candidate).__module__}.{type(candidate).__qualname__}"
        if identity in seen:
            return {"type": type_name}
        seen.add(identity)
        if isinstance(candidate, RecordingModelProvider):
            return {
                "type": type_name,
                "provider": normalize(candidate.provider, seen),
                "metadata": normalize(candidate.provider_metadata, seen),
            }
        try:
            attributes = vars(candidate)
        except TypeError:
            return {"type": type_name}
        state = {
            key: normalize(item, seen)
            for key, item in attributes.items()
            if not callable(item)
            and key
            not in {
                "client",
                "_client",
                "_lock",
                "lock",
                "_filesystem_lock",
                "sink",
            }
        }
        return {"type": type_name, "state": state}

    encoded = json.dumps(
        normalize(value, set()),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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
    supports_tool_calling: bool | None = None
    is_default: bool | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    max_model_len: int | None = Field(default=None, gt=0)
    compatibility_profile: DesktopModelCompatibilityProfile | None = None
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
    supports_tool_calling: bool = True
    is_default: bool = False
    max_tokens: int = Field(default=8192, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    max_model_len: int = Field(default=128_000, gt=0)
    compatibility_profile: DesktopModelCompatibilityProfile | None = None
    model_config = {"extra": "forbid"}


class RunMessage(BaseModel):
    # System/developer instructions are composed by trusted Context providers.
    # The Desktop request boundary accepts conversation facts only.
    role: Literal["user", "assistant"]
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
    fork_source_run_id: str | None = None

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


class _DesktopRunResources:
    def __init__(
        self, sandbox_handle, scope_handles: list[Any], lifecycle=None
    ) -> None:
        self.sandbox_handle = sandbox_handle
        self.scope_handles = scope_handles
        self.lifecycle = lifecycle
        self._closed = False
        self.defer_close = False

    def __getattr__(self, name):
        return getattr(self.sandbox_handle, name)

    async def close(self) -> None:
        if self.defer_close:
            return
        await self.close_now()

    async def close_now(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[BaseException] = []
        for handle in reversed(self.scope_handles):
            try:
                await handle.close()
            except BaseException as exc:
                errors.append(exc)
        self.scope_handles.clear()
        try:
            await self.sandbox_handle.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise errors[0]


class _DesktopDriver:
    def __init__(
        self,
        service: "DesktopV2Service",
        loop,
        workspace: Path,
        sandbox_handle,
        lazy_builder=None,
    ) -> None:
        self.service = service
        self.loop = loop
        self.workspace = workspace
        self.sandbox_handle = sandbox_handle
        self._lazy_builder = lazy_builder
        self._compose_lock = asyncio.Lock()
        self._binding_closed = False
        self._binding_close_lock = asyncio.Lock()
        self._binding_close_task: asyncio.Task[None] | None = None

    async def execute(self, run_id: str, context: RequestContext):
        await self._ensure_composed()
        token = _ACTIVE_EXTENSION_SCOPE_HANDLES.set(self.sandbox_handle.scope_handles)
        try:
            return await self.loop.execute(run_id, context)
        finally:
            _ACTIVE_EXTENSION_SCOPE_HANDLES.reset(token)

    async def resume(self, run_id: str, context: RequestContext):
        await self._ensure_composed()
        token = _ACTIVE_EXTENSION_SCOPE_HANDLES.set(self.sandbox_handle.scope_handles)
        try:
            return await self.loop.resume(run_id, context)
        finally:
            _ACTIVE_EXTENSION_SCOPE_HANDLES.reset(token)

    async def _ensure_composed(self) -> None:
        if self.loop is not None:
            return
        async with self._compose_lock:
            if self.loop is not None:
                return
            if self._lazy_builder is None:
                raise RuntimeError("Desktop driver has no composition builder")
            _resolved, loop, sandbox_handle = await self._lazy_builder()
            self.loop = loop
            self.sandbox_handle = sandbox_handle

    async def on_suspended(self, context: RequestContext) -> None:
        lifecycle = getattr(self.sandbox_handle, "lifecycle", None)
        if lifecycle is not None:
            record = await lifecycle.suspend(
                run_id=self.sandbox_handle.ref.owner_run_id,
                context=context,
            )
            if record is not None and self.service is not None:
                log = (
                    self.service.logger.warning
                    if record.state == ExecutionResourceState.RELEASE_FAILED
                    else self.service.logger.info
                )
                log(
                    "sandbox.lifecycle_settled",
                    "Sandbox suspension lifecycle settled",
                    attributes={
                        "run_id": record.run_id,
                        "generation": record.generation,
                        "state": record.state.value,
                        "disposition": (
                            record.release_disposition.value
                            if record.release_disposition is not None
                            else None
                        ),
                        "compute_released": record.compute_released,
                        "blocking_job_count": len(record.blocking_job_ids),
                        "blocking_child_run_count": len(
                            record.blocking_child_run_ids
                        ),
                        "retry_count": record.retry_count,
                    },
                )
            if (
                record is not None
                and record.state == ExecutionResourceState.RELEASE_BLOCKED
                and record.blocking_job_ids
            ):
                self.sandbox_handle.defer_close = True
                self.service._schedule_blocked_sandbox_cleanup(
                    self.sandbox_handle, lifecycle, record, context
                )

    async def close_binding(self) -> None:
        async with self._binding_close_lock:
            if self._binding_close_task is None:
                self._binding_close_task = asyncio.create_task(
                    self._close_binding_once()
                )
            close_task = self._binding_close_task
        await asyncio.shield(close_task)
        self._binding_closed = True

    async def close(self) -> None:
        """Release all Run-scoped resources at terminal or suspension boundary."""

        await self.close_binding()

    async def _close_binding_once(self) -> None:
        if self.sandbox_handle is None:
            return
        controller = getattr(self.loop, "delegated_run_controller", None)
        controller_close = getattr(controller, "close", None)
        controller_error: BaseException | None = None
        if controller_close is not None:
            try:
                closed = controller_close()
                if inspect.isawaitable(closed):
                    await closed
            except BaseException as exc:
                controller_error = exc
        try:
            await self.sandbox_handle.close()
        except BaseException as sandbox_error:
            if controller_error is not None:
                raise sandbox_error from controller_error
            raise
        if controller_error is not None:
            raise controller_error


class _DesktopRecoveryAgent:
    """Recompose a Desktop driver for a durable Run with lost scheduler work."""

    def __init__(self, service: "DesktopV2Service") -> None:
        self.service = service
        self.runtime = service.driver_runtime

    def _ensure_execution(self, run_id, context, *, resume):
        return asyncio.create_task(
            self._execute(run_id, context, resume=resume),
            name=f"desktop-recovery:{run_id}",
        )

    async def _compose_driver(self, run_id, context):
        command = await self.service.session_store.get_start_command(run_id)
        user_id = context.actor.principal_id
        agent = await self.service._agent(command.agent_id, user_id)
        provider = await self.service._provider(agent, user_id)
        workspace = await self.service.workspace_root(
            command.config.metadata.get("workspace_id"), command.agent_id
        )
        async def build():
            return await self.service._build_loop(
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
                resolved_spec_hash=command.resolved_spec_hash,
                component_snapshot=command.config.metadata.get("runtime_components"),
            )

        driver = _DesktopDriver(
            self.service, None, workspace, None, lazy_builder=build
        )
        self.service._drivers[run_id] = driver
        return driver, agent

    async def _execute(self, run_id, context, *, resume):
        driver, agent = await self._compose_driver(run_id, context)
        memory_enabled = _agent_memory_enabled(
            agent,
            self.service.memory_plugin_id,
            self.service.session_memory_plugin_id,
        )
        facade = SAgent(
            runtime=self.runtime,
            driver_factory=lambda _: driver,
            memory_service=(self.service.memory_service if memory_enabled else None),
            memory_scope={"recall": False, "auto_write": memory_enabled},
        )
        try:
            execution = facade._ensure_execution(run_id, context, resume=resume)
            return await execution
        finally:
            if self.service._drivers.get(run_id) is driver:
                self.service._drivers.pop(run_id, None)

    async def _recover_interrupted_run(self, run_id, context):
        driver, _ = await self._compose_driver(run_id, context)
        try:
            return await driver.loop.recover_interrupted(run_id, context)
        finally:
            await driver.close()
            if self.service._drivers.get(run_id) is driver:
                self.service._drivers.pop(run_id, None)

    async def _fail_driver_crash(self, run_id, error, context):
        facade = SAgent(runtime=self.runtime, driver_factory=lambda _: None)
        return await facade._fail_driver_crash(run_id, error, context)


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
        self.extension_host = ExtensionHost(self.extensions)
        self._scope_handles = []
        self._long_lived_components: dict[tuple[str, ...], tuple[Any, Any]] = {}
        self._long_lived_component_lock = asyncio.Lock()
        self._workspace_initializations: dict[tuple[str, str, str], Path] = {}
        self._workspace_initialization_lock = asyncio.Lock()
        self._sandbox_grant_issuer = SandboxGrantIssuer()
        self._process_scope = self.extension_host.open_scope_sync(
            ExtensionScopeContext(
                scope=ExtensionScope.PROCESS,
                scope_id="desktop-v2",
            ),
            self.extension_host.plan(()),
        )
        self._scope_handles.append(self._process_scope)
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
            {"root": str(self.runtime_root)},
            allow_user_selection=False,
        )
        self.runtime = HarnessRuntime(self.session_store)
        self.scheduler = InMemoryScheduler()
        self.driver_session_store = LeaseFencedSessionStore(
            self.session_store, self.scheduler
        )
        self.driver_runtime = HarnessRuntime(self.driver_session_store)
        self.dispatcher = LocalWorkerDispatcher(
            self.scheduler,
            max_concurrent_runs=8,
            max_concurrent_runs_per_tenant=2,
            lease_scope_factory=self.driver_session_store.lease_scope,
        )
        self.delegation_limiter = DelegationConcurrencyLimiter(
            max_concurrency=8,
            max_per_tenant=2,
        )
        self.dispatcher.attach_recovery_agent(_DesktopRecoveryAgent(self))
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
        self._application_close_tasks: set[asyncio.Task] = set()
        self._sandbox_cleanup_tasks: set[asyncio.Task] = set()
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
            plan = self.extension_host.plan(
                (
                    CapabilityRequirement(
                        capability=capability,
                        api_version=_desktop_component_api_version(capability),
                    ),
                ),
                selections={capability: selected},
                configs={selected: config},
                scope_overrides={selected: ExtensionScope.PROCESS},
            )
            handle = self.extension_host.open_scope_sync(
                ExtensionScopeContext(
                    scope=ExtensionScope.PROCESS,
                    scope_id="desktop-v2",
                ),
                plan,
                parent=None,
            )
            self._scope_handles.append(handle)
            return selected, handle.providers.require_unique(capability)
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
            plan = self.extension_host.plan(
                (
                    CapabilityRequirement(
                        capability=capability,
                        api_version=_desktop_component_api_version(capability),
                    ),
                ),
                selections={capability: default_plugin_id},
                configs={default_plugin_id: config},
                scope_overrides={default_plugin_id: ExtensionScope.PROCESS},
            )
            handle = self.extension_host.open_scope_sync(
                ExtensionScopeContext(
                    scope=ExtensionScope.PROCESS,
                    scope_id="desktop-v2",
                ),
                plan,
            )
            self._scope_handles.append(handle)
            return default_plugin_id, handle.providers.require_unique(capability)

    async def _log_memory_error(self, error: Exception) -> None:
        self.logger.exception(
            "memory.ingestion_failed",
            "Committed Run memory ingestion failed",
            error,
        )

    async def initialize_agent_workspace(self) -> Path:
        settings = await self.get_settings()
        workspace = await self._ensure_agent_workspace(
            settings.agent_workspace_path,
            component_selections=settings.component_selections,
            language=settings.language,
        )
        await self.dispatcher.start()
        await self._recover_pending_sandbox_cleanups()
        return workspace

    async def close(self) -> None:
        observers = tuple(self._run_observers.values())
        self._run_observers.clear()
        for task in observers:
            task.cancel()
        if observers:
            await asyncio.gather(*observers, return_exceptions=True)
        cleanup_tasks = tuple(self._sandbox_cleanup_tasks)
        for task in cleanup_tasks:
            task.cancel()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        await self.dispatcher.close()
        await asyncio.sleep(0)
        close_tasks = tuple(self._application_close_tasks)
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        drivers = tuple(self._drivers.values())
        self._drivers.clear()
        if drivers:
            await asyncio.gather(
                *(driver.close_binding() for driver in drivers),
                return_exceptions=True,
            )
        await self.scheduler.close()
        await self.session_store.close()
        for handle in reversed(self._scope_handles):
            await handle.close()
        self._scope_handles.clear()
        self._long_lived_components.clear()
        self._workspace_initializations.clear()
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
        first_token_latency_total_ms = 0.0
        first_token_latency_samples = 0
        first_token_latencies_ms: list[float] = []
        output_generation_total_ms = 0.0
        output_token_intervals = 0
        output_token_rates: list[float] = []
        skipped_event_sessions: set[str] = set()
        skipped_diagnostic_sessions: set[str] = set()

        agent_records = await self.catalog.list_agents(user_id)
        agent_names = {value.agent_id: value.name for value in agent_records}
        indexed_sessions = await self.session_index.list()

        for session in indexed_sessions:
            session_id = session.session_id
            runs = ()
            events = ()
            requests = ()
            # Runtime events and model diagnostics are independent best-effort
            # projections. Failure in one source must not discard valid data
            # already persisted by the other source.
            try:
                runs = await self.session_store.list_session_runs(session_id)
            except (OSError, ValueError, SageV2Error) as error:
                skipped_event_sessions.add(session_id)
                self.logger.warning(
                    "usage.runs_skipped",
                    "Skipped unreadable Runs while aggregating usage",
                    attributes={
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )
            try:
                events = await self.session_store.read_session_events(session_id)
            except (OSError, ValueError, SageV2Error) as error:
                skipped_event_sessions.add(session_id)
                self.logger.warning(
                    "usage.events_skipped",
                    "Skipped unreadable events while aggregating usage",
                    attributes={
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )
            try:
                requests = await self.diagnostics.list_model_requests(
                    session_id=session_id
                )
            except (OSError, ValueError, SageV2Error) as error:
                skipped_diagnostic_sessions.add(session_id)
                self.logger.warning(
                    "usage.diagnostics_skipped",
                    "Skipped unreadable model diagnostics while aggregating usage",
                    attributes={
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )

            run_agents: dict[str, str] = {}
            for run in runs:
                try:
                    command = await self.session_store.get_start_command(run.run_id)
                    run_agents[run.run_id] = command.agent_id
                except (OSError, ValueError, SageV2Error):
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

                first_token_latency_ms, generation_ms, token_intervals = (
                    _usage_latency_observation(record, output_tokens=output_tokens)
                )
                if first_token_latency_ms is not None:
                    first_token_latency_total_ms += first_token_latency_ms
                    first_token_latency_samples += 1
                    first_token_latencies_ms.append(first_token_latency_ms)
                if generation_ms is not None and token_intervals > 0:
                    output_generation_total_ms += generation_ms
                    output_token_intervals += token_intervals
                    if generation_ms > 0:
                        output_token_rates.append(token_intervals * 1000 / generation_ms)

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
        totals["average_first_token_latency_ms"] = (
            round(first_token_latency_total_ms / first_token_latency_samples, 2)
            if first_token_latency_samples
            else None
        )
        totals["first_token_latency_p50_ms"] = _usage_percentile(
            first_token_latencies_ms, 0.50
        )
        totals["first_token_latency_p95_ms"] = _usage_percentile(
            first_token_latencies_ms, 0.95
        )
        totals["first_token_latency_samples"] = len(first_token_latencies_ms)
        totals["output_tokens_per_second"] = (
            round(output_token_intervals * 1000 / output_generation_total_ms, 2)
            if output_generation_total_ms > 0
            else None
        )
        totals["output_tokens_per_second_p50"] = _usage_percentile(
            output_token_rates, 0.50
        )
        totals["output_tokens_per_second_p95"] = _usage_percentile(
            output_token_rates, 0.95
        )
        totals["output_tokens_per_second_samples"] = len(output_token_rates)
        skipped_sessions = skipped_event_sessions | skipped_diagnostic_sessions
        return {
            "range_days": days,
            "generated_at": now.isoformat(),
            "data_quality": {
                "partial": bool(skipped_sessions),
                "skipped_sessions": len(skipped_sessions),
                "skipped_event_sessions": len(skipped_event_sessions),
                "skipped_diagnostic_sessions": len(skipped_diagnostic_sessions),
            },
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
                    "parent_run_id": command.parent_run_id
                    or metadata.get("fork_source_run_id"),
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
                    "parent_run_id": command.parent_run_id
                    or metadata.get("fork_source_run_id"),
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
            self._skill_summary(name, values[name])
            for name in names
            if name in values and _SKILL_NAME.fullmatch(name)
        ]

    async def list_skill_catalog(self, user_id: str) -> list[dict[str, Any]]:
        del user_id
        values = self._skill_provider().descriptors()
        return [
            self._skill_summary(name, values[name])
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

    async def delete_skill(self, skill_name: str, user_id: str) -> dict[str, Any]:
        target = self._imported_skill_root(skill_name)
        if target is None:
            raise ValueError(f"Imported Skill not found: {skill_name}")

        await asyncio.to_thread(shutil.rmtree, target)
        for agent in await self.catalog.list_agents(user_id):
            available = list(agent.config.get("availableSkills") or [])
            if skill_name not in available:
                continue
            config = {
                **agent.config,
                "availableSkills": [name for name in available if name != skill_name],
            }
            await self.catalog.save_agent(agent.model_copy(update={"config": config}))
        return {"deleted_name": skill_name}

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
                "supports_tool_calling": bool(value.supports_tool_calling),
                "is_default": value.is_default,
                "max_tokens": value.max_tokens,
                "temperature": value.temperature,
                "top_p": value.top_p,
                "max_model_len": value.max_model_len,
                "compatibility_profile": (
                    value.compatibility_profile.model_dump(mode="json")
                    if value.compatibility_profile is not None
                    else None
                ),
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
            supports_tool_calling=request.supports_tool_calling,
            is_default=make_default,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            max_model_len=request.max_model_len,
            compatibility_profile=request.compatibility_profile,
        )
        self._validate_model_route(candidate)
        self._validate_model_compatibility_profile(candidate)
        await self.catalog.save_model_provider(candidate)
        values = await self.list_model_providers(user_id)
        return next(value for value in values if value["id"] == candidate.id)

    async def verify_model_provider_capabilities(
        self,
        request: ModelProviderCreate | ModelProviderPatch,
        user_id: str,
        *,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        """Probe a draft route without persisting it to the Desktop catalog."""

        if provider_id is None:
            if not isinstance(request, ModelProviderCreate):
                raise ValueError("New model capability checks require a complete route")
            keys = [value.strip() for value in request.api_keys if value.strip()]
            if len(keys) > 1:
                raise ValueError("Desktop model providers accept one API key")
            candidate = DesktopModelProviderRecord(
                id=new_id("model_probe"),
                user_id=user_id,
                name=request.name.strip(),
                protocol=request.protocol,
                model=request.model.strip(),
                base_url=request.base_url.strip(),
                api_key=keys[0] if keys else "",
                supports_multimodal=request.supports_multimodal,
                supports_structured_output=request.supports_structured_output,
                supports_tool_calling=request.supports_tool_calling,
                is_default=False,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                max_model_len=request.max_model_len,
            )
        else:
            provider = await self.catalog.get_model_provider(provider_id, user_id)
            if provider is None:
                raise ValueError("Provider not found")
            if not isinstance(request, ModelProviderPatch):
                raise ValueError("Existing model capability checks require a patch")
            updates = request.model_dump(exclude_unset=True, exclude={"api_keys"})
            if "compatibility_profile" in request.model_fields_set:
                updates["compatibility_profile"] = request.compatibility_profile
            if request.api_keys is not None:
                keys = [value.strip() for value in request.api_keys if value.strip()]
                if len(keys) > 1:
                    raise ValueError("Desktop model providers accept one API key")
                updates["api_key"] = keys[0] if keys else ""
            candidate = provider.model_copy(update=updates)

        self._validate_model_route(candidate)
        if not candidate.api_key:
            raise ValueError("An API key is required for capability validation")
        return await self._probe_model_provider_capabilities(candidate)

    async def patch_model_provider(
        self, provider_id: str, patch: ModelProviderPatch, user_id: str
    ) -> dict[str, Any]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("Provider not found")
        updates = patch.model_dump(exclude_unset=True, exclude={"api_keys"})
        if "compatibility_profile" in patch.model_fields_set:
            updates["compatibility_profile"] = patch.compatibility_profile
        route_fields = {
            "protocol",
            "model",
            "base_url",
            "api_key",
            "max_tokens",
            "max_model_len",
            "temperature",
            "top_p",
            "supports_multimodal",
            "supports_structured_output",
            "supports_tool_calling",
        }
        if route_fields.intersection(updates) and "compatibility_profile" not in updates:
            updates["compatibility_profile"] = None
        if patch.api_keys is not None:
            keys = [value.strip() for value in patch.api_keys if value.strip()]
            if len(keys) > 1:
                raise ValueError("Desktop model providers accept one API key")
            updates["api_key"] = keys[0] if keys else ""
            if "compatibility_profile" not in updates:
                updates["compatibility_profile"] = None
        updates["updated_at"] = utc_now()
        candidate = provider.model_copy(update=updates)
        self._validate_model_route(candidate)
        self._validate_model_compatibility_profile(candidate)
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

    @staticmethod
    def _model_compatibility_fingerprint(
        provider: DesktopModelProviderRecord,
    ) -> str:
        payload = {
            "protocol": provider.protocol,
            "base_url": provider.base_url.rstrip("/"),
            "model": provider.model,
            "max_tokens": provider.max_tokens,
            "max_model_len": provider.max_model_len,
            "temperature": provider.temperature,
            "top_p": provider.top_p,
            "credential_sha256": hashlib.sha256(
                provider.api_key.encode("utf-8")
            ).hexdigest(),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @classmethod
    def _validate_model_compatibility_profile(
        cls,
        provider: DesktopModelProviderRecord,
    ) -> None:
        profile = provider.compatibility_profile
        if profile is None:
            return
        expected = cls._model_compatibility_fingerprint(provider)
        if profile.route_fingerprint != expected:
            raise ValueError(
                "model compatibility verification does not match the saved route"
            )
        if (
            provider.protocol == "openai-chat-completions"
            and profile.max_output_tokens_field is None
        ):
            raise ValueError(
                "OpenAI Chat Completions compatibility requires an output token field"
            )
        if (
            provider.protocol != "openai-chat-completions"
            and profile.max_output_tokens_field is not None
        ):
            raise ValueError(
                "output token field compatibility only applies to Chat Completions"
            )
        if profile.schema_version >= 2:
            if profile.effective_max_output_tokens is None:
                raise ValueError(
                    "model compatibility verification requires an effective output limit"
                )
            if profile.effective_max_output_tokens > provider.max_tokens:
                raise ValueError(
                    "effective output limit cannot exceed the configured output limit"
                )
            overlap = set(profile.supported_reasoning_efforts).intersection(
                profile.unsupported_reasoning_efforts
            )
            if overlap:
                raise ValueError(
                    "reasoning effort compatibility results cannot overlap"
                )

    @staticmethod
    async def _probe_model_provider_capabilities(
        provider: DesktopModelProviderRecord,
    ) -> dict[str, Any]:
        credential = CredentialMaterial(
            credential_id="desktop_model_probe",
            secret=SecretStr(provider.api_key),
            source="desktop-settings",
        )
        created_providers: list[Any] = []

        def create_probe_provider(
            *,
            max_output_tokens: int,
            maximum_field: str | None = None,
            reasoning_effort: str | None = None,
            request_extra: dict[str, Any] | None = None,
        ):
            extra = dict(request_extra or {})
            if (
                provider.protocol == "openai-chat-completions"
                and maximum_field is not None
            ):
                extra["max_output_tokens_field"] = maximum_field
            route = ModelRoute(
                provider=provider.protocol,
                base_url=provider.base_url,
                credential="desktop_model_probe",
                model=provider.model,
                request=ModelRequestDefaults(
                    max_output_tokens=max_output_tokens,
                    temperature=provider.temperature,
                    top_p=provider.top_p,
                    reasoning_effort=reasoning_effort,
                    extra=extra,
                ),
                limits=ModelLimits(
                    context_window=provider.max_model_len,
                    max_output_tokens=max_output_tokens,
                ),
                capabilities=ModelCapabilityDeclaration(
                    multimodal=True,
                    structured_output=True,
                    tool_calling=True,
                    reasoning=True,
                    parallel_tool_calls=True,
                ),
            )
            model_provider = create_registered_model_provider(
                route,
                credential,
                provider_instance_id=provider.id,
            )
            created_providers.append(model_provider)
            return model_provider

        def serialize_outcome(outcome) -> dict[str, Any]:
            return {
                "supported": outcome.supported,
                **outcome.model_dump(
                    mode="json",
                    exclude={"name", "status"},
                    exclude_none=True,
                    exclude_defaults=True,
                ),
                "status": outcome.status.value,
            }

        candidates = (provider.max_tokens,) + tuple(
            value for value in _OUTPUT_TOKEN_FALLBACKS if value < provider.max_tokens
        )
        negotiation_provider = create_probe_provider(
            max_output_tokens=provider.max_tokens
        )
        connection_outcome = None
        effective_max_output_tokens = provider.max_tokens
        try:
            for candidate in candidates:
                connection_outcome = await probe_model_connection(
                    negotiation_provider,
                    model_binding=provider.id,
                    max_output_tokens=candidate,
                )
                if connection_outcome.supported:
                    effective_max_output_tokens = candidate
                    break
                if str(connection_outcome.provider_code or "") not in {"400", "422"}:
                    break
            if connection_outcome is None or not connection_outcome.supported:
                details = (
                    serialize_outcome(connection_outcome)
                    if connection_outcome is not None
                    else {}
                )
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.capability_probe_all_failed",
                        category=ErrorCategory.VALIDATION,
                        message="model connection and request dialect negotiation failed",
                        safe_to_resume=True,
                        metadata={
                            "connection": details,
                            "probes": {"connection": details},
                        },
                    )
                )

            resolved_maximum_field = None
            if provider.protocol == "openai-chat-completions":
                resolved_maximum_field = getattr(
                    negotiation_provider, "resolved_max_output_tokens_field", None
                ) or default_chat_completion_token_field(provider.model)

            model_provider = create_probe_provider(
                max_output_tokens=effective_max_output_tokens,
                maximum_field=resolved_maximum_field,
            )
            report = await probe_model_capabilities(
                model_provider,
                model_binding=provider.id,
                max_output_tokens=effective_max_output_tokens,
            )
            probes = {
                outcome.name: serialize_outcome(outcome)
                for outcome in report.outcomes
            }
            if not report.valid:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.capability_probe_all_failed",
                        category=ErrorCategory.VALIDATION,
                        message="all model capability probes failed",
                        safe_to_resume=True,
                        metadata={"probes": probes},
                    )
                )

            reasoning_prompt = (
                "Think carefully about 17 multiplied by 19, then reply with the "
                "number only."
            )
            omit_outcome = await probe_model_connection(
                model_provider,
                model_binding=provider.id,
                max_output_tokens=effective_max_output_tokens,
                prompt=reasoning_prompt,
            )
            disable_strategy = "omit"
            disable_outcomes = {"omit": serialize_outcome(omit_outcome)}
            omit_has_reasoning = bool(omit_outcome.metadata.get("has_reasoning"))
            selected_auxiliary_json_outcome = report.outcome("json_object")
            if omit_outcome.supported and omit_has_reasoning:
                for strategy, extra in _REASONING_DISABLE_EXTRAS.items():
                    if strategy == "omit":
                        continue
                    candidate_provider = create_probe_provider(
                        max_output_tokens=effective_max_output_tokens,
                        maximum_field=resolved_maximum_field,
                        request_extra=extra,
                    )
                    outcome = await probe_model_connection(
                        candidate_provider,
                        model_binding=provider.id,
                        max_output_tokens=effective_max_output_tokens,
                        prompt=reasoning_prompt,
                    )
                    disable_outcomes[strategy] = serialize_outcome(outcome)
                    if (
                        outcome.supported
                        and outcome.metadata.get("has_text") is True
                        and outcome.metadata.get("has_reasoning") is not True
                    ):
                        json_outcome = await probe_model_json_object(
                            candidate_provider,
                            model_binding=provider.id,
                            max_output_tokens=effective_max_output_tokens,
                        )
                        disable_outcomes[strategy]["auxiliary_json"] = (
                            serialize_outcome(json_outcome)
                        )
                        if json_outcome.supported:
                            disable_strategy = strategy
                            selected_auxiliary_json_outcome = json_outcome
                            break

            effort_strategy_results: dict[str, dict[str, Any]] = {}
            for effort_strategy in (
                "reasoning_effort",
                "chat_template_reasoning_effort",
            ):
                reasoning_outcomes: dict[str, dict[str, Any]] = {}
                supported_reasoning_efforts: list[str] = []
                text_only_reasoning_efforts: list[str] = []
                unsupported_reasoning_efforts: list[str] = []
                for effort in _REASONING_EFFORTS:
                    nested_strategy = (
                        effort_strategy == "chat_template_reasoning_effort"
                    )
                    effort_provider = create_probe_provider(
                        max_output_tokens=effective_max_output_tokens,
                        maximum_field=resolved_maximum_field,
                        reasoning_effort=None if nested_strategy else effort,
                        request_extra=(
                            {
                                "chat_template_kwargs": {
                                    "thinking": True,
                                    "reasoning_effort": effort,
                                }
                            }
                            if nested_strategy
                            else None
                        ),
                    )
                    outcome = await probe_model_connection(
                        effort_provider,
                        model_binding=provider.id,
                        max_output_tokens=effective_max_output_tokens,
                        prompt=reasoning_prompt,
                    )
                    text_result = serialize_outcome(outcome)
                    reasoning_outcomes[effort] = {"text": text_result}
                    reasoning_observed = bool(
                        outcome.metadata.get("has_reasoning")
                        or outcome.metadata.get("reasoning_tokens")
                    )
                    text_supported = outcome.supported and (
                        not nested_strategy or reasoning_observed
                    )
                    if text_supported:
                        text_only_reasoning_efforts.append(effort)
                    tool_outcome = None
                    if text_supported and report.supports_tools:
                        tool_outcome = await probe_model_tool_calling(
                            effort_provider,
                            model_binding=provider.id,
                            max_output_tokens=effective_max_output_tokens,
                        )
                        reasoning_outcomes[effort]["with_tools"] = (
                            serialize_outcome(tool_outcome)
                        )
                    runtime_supported = text_supported and (
                        not report.supports_tools
                        or (tool_outcome is not None and tool_outcome.supported)
                    )
                    (
                        supported_reasoning_efforts
                        if runtime_supported
                        else unsupported_reasoning_efforts
                    ).append(effort)
                effort_strategy_results[effort_strategy] = {
                    "supported": supported_reasoning_efforts,
                    "text_only": text_only_reasoning_efforts,
                    "unsupported": unsupported_reasoning_efforts,
                    "outcomes": reasoning_outcomes,
                }

            top_level_efforts = effort_strategy_results["reasoning_effort"]
            nested_efforts = effort_strategy_results[
                "chat_template_reasoning_effort"
            ]
            top_supported = top_level_efforts["supported"]
            nested_supported = nested_efforts["supported"]
            reasoning_effort_strategy = "reasoning_effort"
            if nested_supported and (
                not top_supported
                or (
                    len(top_supported) == len(_REASONING_EFFORTS)
                    and len(nested_supported) < len(top_supported)
                )
            ):
                reasoning_effort_strategy = "chat_template_reasoning_effort"
            selected_efforts = effort_strategy_results[reasoning_effort_strategy]
            supported_reasoning_efforts = selected_efforts["supported"]
            text_only_reasoning_efforts = selected_efforts["text_only"]
            unsupported_reasoning_efforts = selected_efforts["unsupported"]
            reasoning_outcomes = selected_efforts["outcomes"]

            explicit_disable = disable_strategy != "omit"
            if omit_has_reasoning:
                reasoning_behavior = "controllable" if explicit_disable else "always"
            else:
                reasoning_behavior = (
                    "controllable" if supported_reasoning_efforts else "none"
                )
            reasoning_control = {
                "supported": explicit_disable or bool(supported_reasoning_efforts),
                "status": "supported"
                if explicit_disable or supported_reasoning_efforts
                else "unsupported",
                "probed": True,
                "behavior": reasoning_behavior,
                "disable_strategy": disable_strategy,
                "effort_strategy": reasoning_effort_strategy,
                "disable_outcomes": disable_outcomes,
                "supported_efforts": supported_reasoning_efforts,
                "text_only_efforts": text_only_reasoning_efforts,
                "unsupported_efforts": unsupported_reasoning_efforts,
                "effort_outcomes": reasoning_outcomes,
                "effort_strategy_outcomes": effort_strategy_results,
                "auxiliary_json": serialize_outcome(
                    selected_auxiliary_json_outcome
                ),
            }
            probes["reasoning_control"] = reasoning_control
            successful_probes = list(report.successful_probes)
            failed_probes = list(report.failed_probes)
            if reasoning_control["supported"]:
                successful_probes.append("reasoning_control")
            elif "reasoning_control" not in failed_probes:
                failed_probes.append("reasoning_control")
            compatibility_profile = DesktopModelCompatibilityProfile(
                route_fingerprint=DesktopV2Service._model_compatibility_fingerprint(
                    provider
                ),
                max_output_tokens_field=resolved_maximum_field,
                effective_max_output_tokens=effective_max_output_tokens,
                reasoning_disable_strategy=disable_strategy,
                reasoning_behavior=reasoning_behavior,
                reasoning_effort_strategy=reasoning_effort_strategy,
                supported_reasoning_efforts=tuple(supported_reasoning_efforts),
                text_only_reasoning_efforts=tuple(text_only_reasoning_efforts),
                unsupported_reasoning_efforts=tuple(unsupported_reasoning_efforts),
                supports_json_object=report.supports_json_object,
                auxiliary_json_compatible=(
                    selected_auxiliary_json_outcome.supported
                ),
                successful_probes=tuple(successful_probes),
                failed_probes=tuple(failed_probes),
            )
            return {
                "valid": True,
                "successful_probes": successful_probes,
                "failed_probes": failed_probes,
                "skipped_probes": [],
                "connection": probes["connection"],
                "requested_max_output_tokens": provider.max_tokens,
                "effective_max_output_tokens": effective_max_output_tokens,
                "supports_multimodal": report.supports_multimodal,
                "supports_structured_output": report.supports_structured_output,
                "supports_json_object": report.supports_json_object,
                "supports_tool_calling": report.supports_tools,
                "multimodal": probes["multimodal"],
                "structured_output": probes["structured_output"],
                "json_object": probes["json_object"],
                "tool_calling": probes["tool_calling"],
                "reasoning_control": reasoning_control,
                "compatibility_profile": compatibility_profile.model_dump(mode="json"),
                "probes": probes,
                "model": provider.model,
                "base_url": provider.base_url,
            }
        finally:
            closed_clients: set[int] = set()
            for value in created_providers:
                client = getattr(value, "raw_client", None)
                if client is None or id(client) in closed_clients:
                    continue
                closed_clients.add(id(client))
                close = getattr(client, "aclose", None) or getattr(
                    client, "close", None
                )
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result

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
        initialization_key = (str(workspace), plugin_id, language)
        async with self._workspace_initialization_lock:
            if initialization_key in self._workspace_initializations:
                return workspace
            plan = self.extension_host.plan(
                (
                    CapabilityRequirement(
                        capability="workspace.initializer", api_version="2"
                    ),
                ),
                selections={"workspace.initializer": plugin_id},
                configs={plugin_id: {"language": language}},
                scope_overrides={plugin_id: ExtensionScope.AGENT},
            )
            handle = await self.extension_host.open_scope_hierarchy(
                ExtensionScopeContext(
                    scope=ExtensionScope.AGENT,
                    scope_id=f"desktop-agent-workspace:{workspace}",
                ),
                plan,
                parent=self._process_scope,
            )
            try:
                initializer = handle.providers.require_unique("workspace.initializer")
                initialize = initializer.initialize
                if inspect.iscoroutinefunction(initialize):
                    result = initialize(workspace)
                else:
                    result = await asyncio.to_thread(initialize, workspace)
                if inspect.isawaitable(result):
                    await result
            except BaseException:
                await handle.close()
                raise
            self._scope_handles.append(handle)
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
        driver: _DesktopDriver | None = None
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
            request = await self._normalize_desktop_fork_request(request)
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
            async def build_driver():
                return await self._build_loop(
                    agent=agent,
                    provider=provider,
                    workspace=workspace,
                    preferred_skills=tuple(request.preferred_skills),
                    approval_mode=request.approval_mode,
                    invocation_mode=request.invocation_mode,
                    session_id=accepted_handle.session_id,
                    run_id=accepted_handle.run_id,
                    resolved_spec_hash=command.resolved_spec_hash,
                    component_snapshot=command.config.metadata.get(
                        "runtime_components"
                    ),
                )

            driver = _DesktopDriver(
                self, None, workspace, None, lazy_builder=build_driver
            )
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
            facade.attach_dispatcher(self.dispatcher)
            application = self._run_application(
                facade,
                agent_id=request.agent_id,
                composition_hash=command.resolved_spec_hash,
                component_snapshot=command.config.metadata.get("runtime_components"),
            )
            stream = await application.entrypoint().schedule_accepted_run(
                accepted_handle, context
            )
            stream._execution.add_done_callback(
                lambda _completed, app=application: self._schedule_application_close(
                    app
                )
            )
        except asyncio.CancelledError:
            if driver is not None:
                await asyncio.shield(driver.close_binding())
            raise
        except Exception as exc:
            if driver is not None:
                try:
                    await driver.close_binding()
                except BaseException as close_exc:
                    run_logger.exception(
                        "agent.run.start_cleanup_failed",
                        "Agent run resources failed to close after startup failure",
                        close_exc,
                        attributes={"agent_id": request.agent_id},
                    )
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

    async def _normalize_desktop_fork_request(
        self, request: DesktopRunRequest
    ) -> DesktopRunRequest:
        if request.session_concurrency_mode != SessionConcurrencyMode.FORK:
            if request.fork_source_run_id is not None:
                raise ValueError("fork_source_run_id requires fork concurrency mode")
            return request
        if not request.session_id or not request.fork_source_run_id:
            raise ValueError("Desktop fork requires session_id and fork_source_run_id")
        parent = await self.runtime.get_run(request.fork_source_run_id)
        if parent.session_id != request.session_id:
            raise ValueError("fork parent Run does not belong to the parent Session")
        if parent.state not in TERMINAL_RUN_STATES:
            raise ValueError("Desktop can only branch from a terminal Run result")
        if parent.concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED:
            raise ValueError("Desktop cannot branch from an unpublished snapshot Run")
        base_revision = parent.accepted_session_revision + parent.revision
        if (
            request.base_session_revision is not None
            and request.base_session_revision != base_revision
        ):
            raise ValueError(
                "fork base revision does not match the selected Run result"
            )
        return request.model_copy(update={"base_session_revision": base_revision})

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
            if driver is not None and driver.loop is not None
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
            async def build_driver():
                return await self._build_loop(
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
                    resolved_spec_hash=command.resolved_spec_hash,
                    component_snapshot=command.config.metadata.get(
                        "runtime_components"
                    ),
                )

            driver = _DesktopDriver(
                self, None, workspace, None, lazy_builder=build_driver
            )
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
        facade.attach_dispatcher(self.dispatcher)
        application = self._run_application(
            facade,
            agent_id=command.agent_id,
            composition_hash=command.resolved_spec_hash,
            component_snapshot=command.config.metadata.get("runtime_components"),
        )
        task = await application.entrypoint().continue_run(
            run_id,
            self._context(
                user_id,
                language=str(command.config.metadata.get("response_language") or "en"),
            ),
        )
        task.add_done_callback(
            lambda _completed, app=application: self._schedule_application_close(app)
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

    def _run_application(
        self,
        agent: SAgent,
        *,
        agent_id: str,
        composition_hash: str,
        component_snapshot: dict[str, Any] | None = None,
    ) -> SAgentApplication:
        """Expose every Desktop Run through the shared Application boundary."""

        selections = {
            **_DESKTOP_COMPONENT_DEFAULTS,
            **dict((component_snapshot or {}).get("selections") or {}),
        }
        providers = {
            ResolvedProviderBinding(
                capability=capability,
                name="default",
                api_version="2",
                plugin_id=str(plugin_id),
                scope=_desktop_component_scope(capability),
                source="plugin",
            )
            for capability, plugin_id in selections.items()
        }
        for capability, scope in (
            ("session.store", "process"),
            ("model.provider", "agent"),
            ("tool.catalog", "run"),
            ("tool.executor", "run"),
            ("execution.dispatcher", "process"),
            ("observability.diagnostic-sink", "process"),
            ("observability.log-sink", "process"),
        ):
            if any(value.capability == capability for value in providers):
                continue
            providers.add(
                ResolvedProviderBinding(
                    capability=capability,
                    name="default",
                    api_version="2",
                    plugin_id=None,
                    scope=scope,
                    source="desktop-host",
                )
            )
        resolved_plan = ResolvedApplicationPlan(
            package_id=f"desktop.{agent_id}",
            manifest_hash=composition_hash,
            entrypoint_agent_id=agent_id,
            providers=tuple(sorted(providers)),
            dependencies=(),
            composition_hash=composition_hash,
        )
        return SAgentApplication(
            agents={agent_id: agent},
            entrypoint_agent_id=agent_id,
            scope_handles=(),
            services={
                "session.access": AuthorizedSessionAccess(
                    self.session_store, runtime=getattr(agent, "runtime", None)
                ),
                "observability.diagnostic-sink": self.diagnostics,
                "observability.log-sink": self.log_sink,
            },
            adapters={},
            composition_hash=composition_hash,
            resolved_plan=resolved_plan,
        )

    def _schedule_application_close(self, application: SAgentApplication) -> None:
        task = asyncio.create_task(application.close())
        self._application_close_tasks.add(task)

        def completed(value: asyncio.Task) -> None:
            self._application_close_tasks.discard(value)
            if value.cancelled():
                return
            error = value.exception()
            if error is not None:
                self.logger.exception(
                    "application.close_failed",
                    "Per-Run application failed to close",
                    error,
                )

        task.add_done_callback(completed)

    def _schedule_blocked_sandbox_cleanup(
        self, resources, lifecycle, record, context: RequestContext
    ) -> None:
        async def cleanup() -> None:
            try:
                await asyncio.gather(
                    *(
                        lifecycle.job_runtime.wait(job_id)
                        for job_id in record.blocking_job_ids
                    )
                )
                future = await self.dispatcher.submit_cleanup(
                    run_id=record.run_id,
                    context=context,
                    generation=record.generation,
                    operation=lambda: lifecycle.reconcile_run(
                        run_id=record.run_id, context=context
                    ),
                )
                settled = await future
                if settled.state in {
                    ExecutionResourceState.RELEASE_REQUESTED,
                    ExecutionResourceState.RELEASE_FAILED,
                }:
                    self._schedule_sandbox_reconcile_loop(
                        lifecycle=lifecycle,
                        record=settled,
                        context=context,
                    )
            finally:
                resources.defer_close = False
                await resources.close_now()

        task = asyncio.create_task(
            cleanup(), name=f"sandbox-cleanup:{record.run_id}:{record.generation}"
        )
        self._sandbox_cleanup_tasks.add(task)
        task.add_done_callback(self._sandbox_cleanup_tasks.discard)

    async def _recover_pending_sandbox_cleanups(self) -> None:
        """Resume cleanup intents whose owning process disappeared while paused."""

        for record in await self.session_store.list_pending_execution_releases():
            if (
                record.state == ExecutionResourceState.RELEASE_BLOCKED
                and record.release_disposition == SandboxReleaseDisposition.DETACH
            ):
                continue
            try:
                run = await self.session_store.get_run(record.run_id)
                session = await self.session_store.get_session(run.session_id)
                if session.owner is None:
                    continue
                command = await self.session_store.get_start_command(record.run_id)
                context = self._context(
                    session.owner.principal_id,
                    language=str(
                        command.config.metadata.get("response_language") or "en"
                    ),
                )
                provider = await self._scoped_component(
                    "execution.sandbox",
                    (
                        "sage.sandbox.ephemeral"
                        if record.sandbox_ref.provider_id == "sage.sandbox.memory"
                        else record.sandbox_ref.provider_id
                    ),
                    scope=ExtensionScope.PROCESS,
                    scope_id="desktop-sandbox",
                    agent_id=command.agent_id,
                    config={
                        "verification_key": self._sandbox_grant_issuer.verification_key
                    },
                    cache_identity={
                        "verification_key": self._sandbox_grant_issuer.verification_key
                    },
                )
                lifecycle = ExecutionBindingLifecycleCoordinator(
                    sandbox_provider=provider,
                    session_store=self.driver_session_store,
                    job_runtime=InMemoryJobRuntime({}),
                )
                self._schedule_sandbox_reconcile_loop(
                    lifecycle=lifecycle,
                    record=record,
                    context=context,
                )
            except Exception as exc:
                self.logger.warning(
                    "sandbox.cleanup_recovery_failed",
                    "Failed to schedule pending sandbox cleanup",
                    attributes={"run_id": record.run_id, "error": str(exc)},
                )

    def _schedule_sandbox_reconcile_loop(
        self, *, lifecycle, record, context: RequestContext
    ) -> None:
        async def reconcile() -> None:
            current = record
            attempt = current.retry_count
            while current.state in {
                ExecutionResourceState.RELEASE_BLOCKED,
                ExecutionResourceState.RELEASE_REQUESTED,
                ExecutionResourceState.RELEASE_FAILED,
            }:
                if current.next_retry_at is not None:
                    delay = (current.next_retry_at - utc_now()).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(min(delay, 300))
                future = await self.dispatcher.submit_cleanup(
                    run_id=current.run_id,
                    context=context,
                    generation=current.generation,
                    attempt=attempt,
                    operation=lambda: lifecycle.reconcile_run(
                        run_id=current.run_id, context=context
                    ),
                )
                current = await future
                if (
                    current.state == ExecutionResourceState.RELEASE_BLOCKED
                    and current.release_disposition == SandboxReleaseDisposition.DETACH
                ):
                    return
                attempt += 1

        task = asyncio.create_task(
            reconcile(), name=f"sandbox-reconcile:{record.run_id}:{record.generation}"
        )
        self._sandbox_cleanup_tasks.add(task)
        task.add_done_callback(self._sandbox_cleanup_tasks.discard)

    async def _discard_driver_if_terminal(
        self, run_id: str, driver: _DesktopDriver
    ) -> None:
        try:
            run = await self.runtime.get_run(run_id)
        except Exception:
            return
        if run.state in TERMINAL_RUN_STATES or run.state == RunState.SUSPENDED:
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
        resolved_spec_hash: str | None = None,
        component_snapshot: dict[str, Any] | None = None,
        force_leaf: bool = False,
    ):
        provisioned: list[Any] = []
        scope_handles: list[Any] = []
        token = _ACTIVE_EXTENSION_SCOPE_HANDLES.set(scope_handles)
        try:
            (
                resolved,
                loop,
                sandbox_handle,
                sandbox_provider,
                sandbox_spec,
                job_runtime,
            ) = await self._compose_run_driver(
                agent=agent,
                provider=provider,
                workspace=workspace,
                preferred_skills=preferred_skills,
                approval_mode=approval_mode,
                invocation_mode=invocation_mode,
                session_id=session_id,
                run_id=run_id,
                resolved_spec_hash=resolved_spec_hash,
                component_snapshot=component_snapshot,
                force_leaf=force_leaf,
                sandbox_observer=provisioned.append,
            )
            lifecycle = None
            if run_id is not None and resolved_spec_hash is not None:
                lifecycle = ExecutionBindingLifecycleCoordinator(
                    sandbox_provider=sandbox_provider,
                    session_store=self.driver_session_store,
                    job_runtime=job_runtime,
                )
            return (
                resolved,
                loop,
                _DesktopRunResources(sandbox_handle, scope_handles, lifecycle),
            )
        except BaseException as exc:
            cleanup_errors: list[BaseException] = []
            # Run-scoped services may still own jobs against the sandbox, so
            # release them before tearing down the execution boundary.
            for handle in reversed(scope_handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    cleanup_errors.append(close_exc)
            for sandbox_handle in reversed(provisioned):
                try:
                    await sandbox_handle.close()
                except BaseException as close_exc:
                    cleanup_errors.append(close_exc)
            if cleanup_errors:
                raise exc from cleanup_errors[0]
            raise
        finally:
            _ACTIVE_EXTENSION_SCOPE_HANDLES.reset(token)

    async def _compose_run_driver(
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
        resolved_spec_hash: str | None = None,
        component_snapshot: dict[str, Any] | None = None,
        force_leaf: bool = False,
        sandbox_observer,
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
        if component_snapshot:
            settings = settings.model_copy(
                update={
                    "component_selections": dict(
                        component_snapshot.get("selections") or {}
                    ),
                    "component_configs": dict(component_snapshot.get("configs") or {}),
                }
            )
        current_resolved_spec_hash = self._desktop_spec_hash(
            resolved.manifest_hash, settings
        )
        estimator_id = settings.component_selections.get(
            "context.token-estimator",
            _DESKTOP_COMPONENT_DEFAULTS["context.token-estimator"],
        )
        reducer_id = settings.component_selections.get(
            "context.reducer", _DESKTOP_COMPONENT_DEFAULTS["context.reducer"]
        )
        estimator_id = _stable_component_id("context.token-estimator", estimator_id)
        reducer_id = _stable_component_id("context.reducer", reducer_id)
        # Desktop compression uses the configured route itself. The summary is
        # derived state in SummaryStore; canonical Session events remain intact.
        # Recording the secondary request also keeps provider diagnostics honest.
        model_provider = await self._model_provider(provider, agent)
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
            await self._model_provider(judge_provider, agent, enable_thinking=False),
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
            await self._model_provider(judge_provider, agent, enable_thinking=False),
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
            await self._model_provider(judge_provider, agent, enable_thinking=False),
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
        memory_query_generator = await self._scoped_component(
            "memory.recall-query",
            memory_query_plugin_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-memory-query:{agent.user_id}:{agent.agent_id}",
            agent_id=agent.agent_id,
            config=(
                {"model": memory_query_model, "language": settings.language}
                if memory_query_plugin_id == "sage.memory.recall-query.llm"
                else {}
            ),
            cache_identity={
                "plugin": memory_query_plugin_id,
                "language": settings.language,
                "provider": judge_provider.id,
                "model": judge_provider.model,
                "base_url": judge_provider.base_url,
                "credential": SecretStr(judge_provider.api_key or ""),
            },
        )
        summarizer_plugin_id = _stable_component_id(
            "context.summarizer",
            settings.component_selections.get(
                "context.summarizer",
                _DESKTOP_COMPONENT_DEFAULTS["context.summarizer"],
            ),
        )
        summarizer = await self._scoped_component(
            "context.summarizer",
            summarizer_plugin_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-summarizer:{agent.user_id}:{agent.agent_id}",
            agent_id=agent.agent_id,
            config={"model": recording_model, "model_binding": "summary"},
            cache_identity={
                "plugin": summarizer_plugin_id,
                "provider": provider.id,
                "model": provider.model,
                "base_url": provider.base_url,
                "credential": SecretStr(provider.api_key or ""),
                "model_binding": "summary",
            },
        )
        token_estimator = await self._scoped_component(
            "context.token-estimator",
            estimator_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-estimator:{agent.user_id}:{agent.agent_id}",
            agent_id=agent.agent_id,
            config={},
        )
        reducer_config = {"estimator": token_estimator}
        if reducer_id == "sage.context.reducer.persistent-summary":
            reducer_config.update(
                {
                    "store": self.summary_store,
                    "summarizer": summarizer,
                }
            )
        context_reducer = await self._scoped_component(
            "context.reducer",
            reducer_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-reducer:{agent.user_id}:{agent.agent_id}",
            agent_id=agent.agent_id,
            config=reducer_config,
            cache_identity={
                "plugin": reducer_id,
                "estimator": estimator_id,
                "summarizer": summarizer_plugin_id,
                "summary_store": self.summary_store_plugin_id,
                "provider": provider.id,
                "model": provider.model,
            },
        )
        continuation_plugin_id = _stable_component_id(
            "agent.continuation-policy",
            settings.component_selections.get(
                "agent.continuation-policy",
                _DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"],
            ),
        )
        if (
            continuation_plugin_id
            in {
                "sage.agent.continuation.llm-judge",
                "sage.agent.continuation.hybrid",
            }
            and not self._auxiliary_json_compatible(judge_provider)
        ):
            continuation_plugin_id = "sage.agent.continuation.deterministic"
        factory = AgentCompositionFactory(
            self.driver_runtime,
            context_components=ContextComponentBundle(
                token_estimator=token_estimator,
                summary_store=self.summary_store,
                summarizer=summarizer,
            ),
        )
        await self._ensure_agent_workspace(
            settings.agent_workspace_path,
            component_selections=settings.component_selections,
            language=settings.language,
        )
        sandbox_plugin_id, sandbox_config = _resolved_sandbox_config(settings)
        workspace_root = _sandbox_workspace_root(sandbox_config, workspace)
        issuer = self._sandbox_grant_issuer
        sandbox_provider = await self._scoped_component(
            "execution.sandbox",
            sandbox_plugin_id,
            scope=ExtensionScope.PROCESS,
            scope_id="desktop-sandbox",
            agent_id=agent.agent_id,
            config={"verification_key": issuer.verification_key},
            cache_identity={"verification_key": issuer.verification_key},
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
        # The bundled local-workspace provider reports IsolationLevel.NONE.
        # Plan mode must be genuinely read-only, so do not expose host process
        # execution when no enforceable OS isolation boundary exists.
        if (
            invocation_mode == "plan"
            and capabilities.isolation_level == IsolationLevel.NONE
        ):
            process_enabled = False
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
        sandbox_spec = ResolvedSandboxSpec(
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
                lifecycle=LifecyclePolicy(
                    durability=(
                        SandboxDurability.DURABLE_EXTERNAL
                        if sandbox_config["workspace_mapping"] == "active_workspace"
                        else SandboxDurability.SNAPSHOTABLE
                    ),
                    safe_pause_behavior=(
                        SandboxReleaseDisposition.TERMINATE
                        if sandbox_config["workspace_mapping"] == "active_workspace"
                        else SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE
                    ),
                    unsafe_pause_behavior=SandboxReleaseDisposition.DETACH,
                ),
                policy_hash=f"sha256:{fingerprint}",
                metadata=sandbox_metadata,
        )
        sandbox_context = self._context(agent.user_id, language=settings.language)
        lifecycle_run_exists = False
        if run_id is not None and resolved_spec_hash is not None:
            try:
                await self.driver_session_store.get_run(run_id)
                lifecycle_run_exists = True
            except SageV2Error as exc:
                if exc.info.code not in {"run.not_found", "run_id.not_found"}:
                    raise
        if lifecycle_run_exists:
            acquisition = ExecutionBindingLifecycleCoordinator(
                sandbox_provider=sandbox_provider,
                session_store=self.driver_session_store,
                job_runtime=None,
            )
            sandbox_handle = await acquisition.acquire(
                run_id=run_id,
                spec=sandbox_spec,
                run_resolved_spec_hash=resolved_spec_hash,
                context=sandbox_context,
            )
        else:
            sandbox_handle = await sandbox_provider.provision(
                sandbox_spec,
                sandbox_context,
                run_id=run_id or new_id("desktop_sandbox"),
            )
        sandbox_observer(sandbox_handle)
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
        goal_state_service = GoalStateService(self.driver_session_store)
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
        if (
            tool_selection_plugin_id == "sage.tool-selection.llm"
            and not self._auxiliary_json_compatible(judge_provider)
        ):
            tool_selection_plugin_id = "sage.tool-selection.lexical"
        configured_tool_selection = settings.component_configs.get(
            "tool.selection-policy"
        )
        tool_selection_config = _tool_selection_component_config(
            tool_selection_plugin_id,
            configured_tool_selection
            if configured_tool_selection is not None
            else legacy_tool_selection_config,
        )
        tool_selection_policy = await self._scoped_component(
            "tool.selection-policy",
            tool_selection_plugin_id,
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-tool-selection:{agent.user_id}:{agent.agent_id}",
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
        active_scope_handles = _ACTIVE_EXTENSION_SCOPE_HANDLES.get()
        if active_scope_handles is not None:
            active_scope_handles.append(official_runtime)
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
                and not (invocation_mode == "plan" and value in _PLAN_BLOCKED_TOOLS)
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
                and not (invocation_mode == "plan" and value in _PLAN_BLOCKED_TOOLS)
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
                await self._model_provider(member_provider, member),
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
                await self._model_provider(
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
        if invocation_mode == "plan":
            member_descriptors = [
                value.model_copy(
                    update={
                        "tools": tuple(
                            tool
                            for tool in value.tools
                            if tool not in _PLAN_BLOCKED_TOOLS
                        )
                    }
                )
                for value in member_descriptors
            ]

        member_registry = AgentRegistry(tuple(member_descriptors))

        async def compose_mode_loop(descriptor, run_id, catalog, executor):
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
            base_continuation_policy = await self._scoped_component(
                "agent.continuation-policy",
                continuation_plugin_id,
                scope=ExtensionScope.RUN,
                scope_id=f"desktop-continuation:{descriptor.agent_id}:{run_id}",
                agent_id=descriptor.agent_id,
                run_id=run_id,
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
            return factory.create_engine(
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
                    reducer=(context_reducer if context_budget is not None else None),
                    estimator=token_estimator,
                    history_reader=self.driver_session_store,
                    projection_observer=self.session_memory_service,
                ),
                expected_resolved_spec_hash=current_resolved_spec_hash,
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
            child_command = await self.session_store.get_start_command(child_run_id)
            _, child_loop, child_sandbox = await self._build_loop(
                agent=member,
                provider=member_provider,
                workspace=workspace,
                preferred_skills=(),
                approval_mode=approval_mode,
                invocation_mode="normal",
                session_id=child_run.session_id,
                run_id=child_run_id,
                resolved_spec_hash=child_command.resolved_spec_hash,
                component_snapshot=child_command.config.metadata.get(
                    "runtime_components"
                ),
                force_leaf=descriptor.mode != AgentMode.TEAM,
            )
            return child_loop, child_sandbox

        mode_factory = ModeAwareAgentLoopFactory(
            runtime=self.driver_runtime,
            model_factory=lambda descriptor, run_id: models_by_agent.get(
                descriptor.agent_id, recording_model
            ),
            base_catalog=native_catalog,
            base_executor=native_executor,
            registry=member_registry,
            resolved_spec_hash=current_resolved_spec_hash,
            max_delegation_concurrency=4,
            delegation_concurrency_limiter=self.delegation_limiter,
            loop_composer=compose_mode_loop,
            workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
            fallback_invocation_mode=invocation_mode,
            child_loop_factory=compose_child_loop,
        )
        loop = await mode_factory.create_loop_async(
            root_descriptor, run_id or "pending"
        )
        return (
            resolved,
            loop,
            sandbox_handle,
            sandbox_provider,
            sandbox_spec,
            official_runtime.job_runtime,
        )

    async def _scoped_component(
        self,
        capability: str,
        plugin_id: str,
        *,
        scope: ExtensionScope,
        scope_id: str,
        config: dict[str, Any],
        agent_id: str | None = None,
        run_id: str | None = None,
        cache_identity: Any | None = None,
    ):
        cache_key: tuple[str, ...] | None = None
        if scope in {
            ExtensionScope.PROCESS,
            ExtensionScope.TENANT,
            ExtensionScope.AGENT,
        }:
            cache_key = (
                scope.value,
                scope_id,
                capability,
                plugin_id,
                _component_cache_fingerprint(
                    config if cache_identity is None else cache_identity
                ),
            )
            cached = self._long_lived_components.get(cache_key)
            if cached is not None:
                return cached[1]

        lock_acquired = False
        if cache_key is not None:
            await self._long_lived_component_lock.acquire()
            lock_acquired = True
            cached = self._long_lived_components.get(cache_key)
            if cached is not None:
                self._long_lived_component_lock.release()
                return cached[1]
        handle = None
        try:
            plan = self.extension_host.plan(
                (
                    CapabilityRequirement(
                        capability=capability,
                        api_version=_desktop_component_api_version(capability),
                    ),
                ),
                selections={capability: plugin_id},
                configs={plugin_id: config},
                scope_overrides={plugin_id: scope},
            )
            parents = [self._process_scope]
            if scope == ExtensionScope.RUN:
                agent_parent = await self.extension_host.open_scope(
                    ExtensionScopeContext(
                        scope=ExtensionScope.AGENT,
                        scope_id=f"desktop-agent-scope:{agent_id or 'default'}",
                        agent_id=agent_id,
                    ),
                    self.extension_host.plan(()),
                    parent=self._process_scope,
                )
                owner_handles = _ACTIVE_EXTENSION_SCOPE_HANDLES.get()
                (
                    owner_handles if owner_handles is not None else self._scope_handles
                ).append(agent_parent)
                parents.append(agent_parent)
            handle = await self.extension_host.open_scope_hierarchy(
                ExtensionScopeContext(
                    scope=scope,
                    scope_id=scope_id,
                    agent_id=agent_id,
                    run_id=run_id,
                ),
                plan,
                parent=parents[-1] if scope != ExtensionScope.PROCESS else None,
            )
            provider = handle.providers.require_unique(capability)
            if cache_key is not None:
                self._scope_handles.append(handle)
                self._long_lived_components[cache_key] = (handle, provider)
            else:
                owner_handles = _ACTIVE_EXTENSION_SCOPE_HANDLES.get()
                (
                    owner_handles if owner_handles is not None else self._scope_handles
                ).append(handle)
            return provider
        except BaseException:
            if handle is not None:
                await handle.close()
            raise
        finally:
            if lock_acquired:
                self._long_lived_component_lock.release()

    async def _session_id_for_run(self, run_id: str) -> str:
        return (await self.session_store.get_run(run_id)).session_id

    def _manifest(self, agent, provider, tools, skills):
        max_steps = max(1, min(int(agent.config.get("maxLoopCount") or 24), 200))
        deep_thinking, thinking_level = self._thinking_config(agent)
        compatibility_profile = self._verified_model_compatibility_profile(provider)
        effective_max_output_tokens = self._effective_model_output_tokens(
            provider, compatibility_profile
        )
        reasoning_effort = self._effective_reasoning_effort(
            compatibility_profile,
            enabled=deep_thinking,
            requested=thinking_level,
            legacy=thinking_level if deep_thinking else None,
        )
        request_extra: dict[str, Any] = {}
        if (
            provider.protocol == "openai-chat-completions"
            and compatibility_profile is not None
        ):
            request_extra["max_output_tokens_field"] = (
                compatibility_profile.max_output_tokens_field
            )
        if compatibility_profile is not None and not deep_thinking:
            request_extra.update(
                self._reasoning_disable_extra(
                    compatibility_profile.reasoning_disable_strategy
                )
            )
        elif compatibility_profile is not None:
            request_extra.update(
                self._reasoning_effort_extra(
                    compatibility_profile,
                    enabled=deep_thinking,
                    requested=thinking_level,
                )
            )
        memory_enabled = (
            self.memory_plugin_id != "sage.memory.noop" and "search_memory" in tools
        )
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=effective_max_output_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=request_extra,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=effective_max_output_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=provider.supports_tool_calling,
                reasoning=True,
                parallel_tool_calls=provider.supports_tool_calling,
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
                    tools=tools if provider.supports_tool_calling else (),
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

    async def _model_provider(
        self, provider, agent, *, enable_thinking: bool | None = None
    ):
        deep_thinking, thinking_level = self._thinking_config(agent)
        if enable_thinking is not None:
            deep_thinking = enable_thinking
        request_extra: dict[str, Any] = {}
        compatibility_profile = self._verified_model_compatibility_profile(provider)
        effective_max_output_tokens = self._effective_model_output_tokens(
            provider, compatibility_profile
        )
        reasoning_effort = self._effective_reasoning_effort(
            compatibility_profile,
            enabled=deep_thinking,
            requested=thinking_level,
            legacy=thinking_level if deep_thinking else None,
        )
        if provider.protocol == "openai-chat-completions":
            if compatibility_profile is not None:
                request_extra["max_output_tokens_field"] = (
                    compatibility_profile.max_output_tokens_field
                )
                if not deep_thinking:
                    request_extra.update(
                        self._reasoning_disable_extra(
                            compatibility_profile.reasoning_disable_strategy
                        )
                    )
                else:
                    request_extra.update(
                        self._reasoning_effort_extra(
                            compatibility_profile,
                            enabled=True,
                            requested=thinking_level,
                        )
                    )
            elif enable_thinking is not None:
                request_extra["reasoning_parameter_fallback"] = (
                    enable_thinking is False
                )
                # There is no portable "thinking disabled" field. In
                # particular, minimal is still reasoning and some compatible
                # gateways reject reasoning_effort entirely. Auxiliary
                # requests therefore use provider defaults for OpenAI
                # reasoning models; vendor-specific disable controls remain for
                # protocols where Sage has an explicit mapping.
                if enable_thinking or not is_openai_reasoning_model(provider.model):
                    request_extra.update(
                        build_llm_extra_body(
                            provider.model,
                            base_url=provider.base_url,
                            enable_thinking=enable_thinking,
                            thinking_level=(
                                thinking_level if enable_thinking else None
                            ),
                            default_off="minimal",
                        )
                    )
        elif provider.protocol == "openai-responses":
            if compatibility_profile is not None and not deep_thinking:
                request_extra.update(
                    self._reasoning_disable_extra(
                        compatibility_profile.reasoning_disable_strategy
                    )
                )
            elif compatibility_profile is not None:
                request_extra.update(
                    self._reasoning_effort_extra(
                        compatibility_profile,
                        enabled=True,
                        requested=thinking_level,
                    )
                )
            elif enable_thinking is not None:
                request_extra["reasoning_parameter_fallback"] = (
                    enable_thinking is False
                )
        elif compatibility_profile is not None and not deep_thinking:
            request_extra.update(
                self._reasoning_disable_extra(
                    compatibility_profile.reasoning_disable_strategy
                )
            )
        elif compatibility_profile is not None:
            request_extra.update(
                self._reasoning_effort_extra(
                    compatibility_profile,
                    enabled=True,
                    requested=thinking_level,
                )
            )
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=effective_max_output_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=request_extra,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=effective_max_output_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=provider.supports_tool_calling,
                reasoning=True,
                parallel_tool_calls=provider.supports_tool_calling,
            ),
        )
        protocol = resolve_model_protocol(route.provider)
        return await self._scoped_component(
            "model.provider",
            f"sage.model.{protocol.value}",
            scope=ExtensionScope.AGENT,
            scope_id=f"desktop-agent:{agent.user_id}:{agent.agent_id}",
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
        )

    @classmethod
    def _verified_model_compatibility_profile(
        cls,
        provider: DesktopModelProviderRecord,
    ) -> DesktopModelCompatibilityProfile | None:
        profile = provider.compatibility_profile
        if profile is None:
            return None
        if profile.route_fingerprint != cls._model_compatibility_fingerprint(provider):
            return None
        return profile

    @staticmethod
    def _effective_model_output_tokens(
        provider: DesktopModelProviderRecord,
        profile: DesktopModelCompatibilityProfile | None,
    ) -> int:
        if profile is not None and profile.effective_max_output_tokens is not None:
            return profile.effective_max_output_tokens
        return provider.max_tokens

    @classmethod
    def _auxiliary_json_compatible(
        cls,
        provider: DesktopModelProviderRecord,
    ) -> bool:
        profile = cls._verified_model_compatibility_profile(provider)
        return (
            profile is None
            or profile.schema_version < 2
            or profile.auxiliary_json_compatible
        )

    @staticmethod
    def _effective_reasoning_effort(
        profile: DesktopModelCompatibilityProfile | None,
        *,
        enabled: bool,
        requested: str,
        legacy: str | None,
    ) -> str | None:
        if not enabled:
            return None
        if profile is None:
            return legacy
        if profile.schema_version < 2:
            return None
        if profile.reasoning_effort_strategy != "reasoning_effort":
            return None
        if requested in profile.supported_reasoning_efforts:
            return requested
        return None

    @staticmethod
    def _reasoning_disable_extra(strategy: str) -> dict[str, Any]:
        return dict(_REASONING_DISABLE_EXTRAS.get(strategy, {}))

    @staticmethod
    def _reasoning_effort_extra(
        profile: DesktopModelCompatibilityProfile,
        *,
        enabled: bool,
        requested: str,
    ) -> dict[str, Any]:
        if (
            enabled
            and profile.schema_version >= 2
            and profile.reasoning_effort_strategy
            == "chat_template_reasoning_effort"
            and requested in profile.supported_reasoning_efforts
        ):
            return {
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": requested,
                }
            }
        return {}

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
            "runtime_components": {
                "selections": dict(settings.component_selections),
                "configs": dict(settings.component_configs),
            },
        }
        if request.fork_source_run_id is not None:
            metadata["fork_source_run_id"] = request.fork_source_run_id
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
            base_tools = tuple(
                name
                for name in (run_config.enabled_tools or ())
                if not (
                    request.invocation_mode == "plan" and name in _PLAN_BLOCKED_TOOLS
                )
            )
            enabled_tools = (
                *base_tools,
                *(name for name in invocation_grants if name not in base_tools),
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
            resolved_spec_hash=self._desktop_spec_hash(
                resolved.manifest_hash, settings
            ),
            idempotency_key=request.idempotency_key or new_id("desktop_request"),
            session_concurrency_mode=request.session_concurrency_mode,
            base_session_revision=request.base_session_revision,
            invocation_mode=request.invocation_mode,
        )

    def _desktop_spec_hash(self, manifest_hash: str, settings) -> str:
        components = {
            capability: _stable_component_id(
                capability,
                settings.component_selections.get(capability, default_plugin),
            )
            for capability, default_plugin in _DESKTOP_COMPONENT_DEFAULTS.items()
        }
        process_plugins = {
            "session.store": self.session_plugin_id,
            "context.summary-store": self.summary_store_plugin_id,
            "observability.diagnostic-sink": self.diagnostic_plugin_id,
            "memory.provider": self.memory_plugin_id,
            "session-memory.provider": self.session_memory_plugin_id,
        }
        selected_plugins = set(components.values()) | set(process_plugins.values())
        versions = {
            plugin_id: self.extensions.get(plugin_id).descriptor.version
            for plugin_id in sorted(selected_plugins)
            if self.extensions.contains(plugin_id)
        }
        payload = {
            "manifest": manifest_hash,
            "components": components,
            "configs": dict(settings.component_configs),
            "process_plugins": process_plugins,
            "plugin_versions": versions,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

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
    return _usage_timestamp(record.get("completed_at") or record.get("started_at"))


def _usage_percentile(samples: list[float], percentile: float) -> float | None:
    """Return a linearly interpolated percentile for one usage sample series."""

    if not samples:
        return None
    ordered = sorted(samples)
    position = (len(ordered) - 1) * min(1.0, max(0.0, percentile))
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 2)


def _usage_latency_observation(
    record: dict[str, Any], *, output_tokens: int
) -> tuple[float | None, float | None, int]:
    started_at = _usage_timestamp(record.get("started_at"))
    first_token_at = _usage_timestamp(record.get("first_token_at"))
    completed_at = _usage_timestamp(record.get("completed_at"))

    first_token_latency_ms: float | None = None
    if isinstance(record.get("ttfb_ms"), (int, float)) and record["ttfb_ms"] >= 0:
        first_token_latency_ms = float(record["ttfb_ms"])
    elif started_at is not None and first_token_at is not None:
        seconds = (first_token_at - started_at).total_seconds()
        if seconds >= 0:
            first_token_latency_ms = seconds * 1000
    elif isinstance(record.get("ttfb_sec"), (int, float)):
        seconds = float(record["ttfb_sec"])
        if seconds >= 0:
            first_token_latency_ms = seconds * 1000

    token_intervals = max(0, output_tokens - 1)
    generation_ms: float | None = None
    if token_intervals > 0:
        if (
            isinstance(record.get("duration_ms"), (int, float))
            and first_token_latency_ms is not None
        ):
            seconds = (float(record["duration_ms"]) - first_token_latency_ms) / 1000
            if seconds >= 0:
                generation_ms = seconds * 1000
        elif first_token_at is not None and completed_at is not None:
            seconds = (completed_at - first_token_at).total_seconds()
            if seconds >= 0:
                generation_ms = seconds * 1000
        elif first_token_latency_ms is not None and isinstance(
            record.get("duration_sec"), (int, float)
        ):
            seconds = float(record["duration_sec"]) - (first_token_latency_ms / 1000)
            if seconds >= 0:
                generation_ms = seconds * 1000
    return first_token_latency_ms, generation_ms, token_intervals


def _usage_timestamp(raw: Any) -> datetime | None:
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
