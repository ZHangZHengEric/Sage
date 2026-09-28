from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

class ModelBody(BaseModel):
    id: str | None = None
    protocol: str = "openai-chat-completions"
    base_url: str = "https://api.openai.com/v1"
    model: str
    api_key: str = ""
    is_default: bool = True

class AgentBody(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str = ""
    tools: list[str] = Field(default_factory=list)

class AgentPublic(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str | None = None
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

class ToolPublic(BaseModel):
    name: str
    category: str = ""
    source: str = "official"
    default: bool = False

class McpBody(BaseModel):
    name: str
    protocol: Literal["sse", "streamable_http"] = "streamable_http"
    url: str | None = None
    api_key: str = ""
    disabled: bool = False
    description: str = ""

class McpPublic(BaseModel):
    name: str
    protocol: str
    url: str | None = None
    disabled: bool = False
    description: str = ""
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

class ModelPublic(BaseModel):
    id: str
    protocol: str
    base_url: str
    model: str
    is_default: bool

