from __future__ import annotations

from typing import Literal
from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from pydantic import BaseModel, ConfigDict, Field
from app.v2.server.runtime.policy import ExecutionPolicy
from sagents.v2.package.manifest.agents import AgentSandboxConfig, AgentBudgets, AgentMemoryBehavior
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.package.manifest.runtime import CapabilitySelection

from app.v2.server.catalog.records import ModelConfiguration
from app.v2.server.runtime.official import default_agent_tools

class ModelBody(ModelConfiguration):
    id: str | None = None
    protocol: str = "openai-chat-completions"
    base_url: str | None = None
    model: str
    api_key: str = ""
    is_default: bool = True

class AgentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str = ""
    fast_model_id: str | None = None
    tools: list[str] = Field(default_factory=default_agent_tools)
    external_tools: list[str] = Field(default_factory=list)
    tool_approval: ToolApprovalConfig | None = None
    execution_policy: ExecutionPolicy | None = None
    sandbox: AgentSandboxConfig | None = None
    budgets: AgentBudgets | None = None
    memory: AgentMemoryBehavior | None = None
    plugins: dict[str, CapabilitySelection] | None = None

class AgentPublic(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str | None = None
    fast_model_id: str | None = None
    tools: list[str] = Field(default_factory=list)
    external_tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tool_approval: ToolApprovalConfig | None = None
    execution_policy: ExecutionPolicy = Field(default_factory=lambda: ExecutionPolicy(shell="sandboxed"))
    sandbox: AgentSandboxConfig = Field(default_factory=AgentSandboxConfig)
    package: AgentPackageBundle | None = None
    package_ref: str | None = None

class AgentSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    model_id: str = ""
    model_name: str = ""
    tool_count: int
    skill_count: int

class ToolPublic(BaseModel):
    approval_key: str | None = None
    name: str
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict)
    side_effect_level: str = "none"
    requires_approval: bool = False
    category: str = ""
    source: str = "official"
    default: bool = False

class AgentToolOption(BaseModel):
    name: str
    description: str = ""
    approval_key: str | None = None
    category: str = ""
    source: str = "official"
    default: bool = False

class AgentModelOption(BaseModel):
    id: str
    model: str
    is_default: bool

class AgentSkillOption(BaseModel):
    skill_id: str
    name: str
    description: str

class AgentExternalToolGroup(BaseModel):
    source: Literal["mcp", "a2a"]
    name: str
    tools: list[str]

class AgentEditorResources(BaseModel):
    models: list[AgentModelOption]
    skills: list[AgentSkillOption]
    tools: list[AgentToolOption]
    external_tools: list[str]
    external_tool_groups: list[AgentExternalToolGroup] = Field(default_factory=list)
    plugins: dict[str, object] | None = None

class McpBody(BaseModel):
    name: str
    protocol: Literal["sse", "streamable_http"] = "streamable_http"
    url: str | None = None
    api_key: str = ""
    disabled: bool = False
    description: str = ""
    timeout_seconds: float | None = Field(default=None, gt=0, le=900)
    call_timeout_seconds: float | None = Field(default=7200, gt=0, allow_inf_nan=False)

class McpPublic(BaseModel):
    name: str
    protocol: str
    url: str | None = None
    disabled: bool = False
    description: str = ""
    timeout_seconds: float = 30
    call_timeout_seconds: float | None = None
    tools: list[str] = Field(default_factory=list)
    has_api_key: bool = False

class A2AAgentBody(BaseModel):
    """A remote A2A agent this tenant's Agents may delegate to.

    ``url`` is the peer's base URL. Its Agent Card, fetched from the well-known
    path under that base, is what names the skills and the RPC endpoint — so
    there is nothing else to configure and nothing here to keep in sync when
    the peer changes.
    """

    name: str
    url: str | None = None
    api_key: str = ""
    disabled: bool = False
    description: str = ""

class A2AAgentPublic(BaseModel):
    name: str
    url: str | None = None
    disabled: bool = False
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    has_api_key: bool = False

class ModelPublic(ModelConfiguration):
    id: str
    protocol: str
    base_url: str
    model: str
    is_default: bool


class ModelDetail(ModelPublic):
    api_key: str
