from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.desktop_v2.backend.catalog import DesktopModelCompatibilityProfile
from sagents.v2.contracts.run_state import SessionConcurrencyMode


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


__all__ = [
    "AgentCreate",
    "AgentSettingsPatch",
    "ComponentSelectionRequest",
    "DesktopProject",
    "DesktopRunRequest",
    "DesktopV2Settings",
    "MCPConnectionRequest",
    "ModelProviderCreate",
    "ModelProviderPatch",
    "RunMessage",
]
