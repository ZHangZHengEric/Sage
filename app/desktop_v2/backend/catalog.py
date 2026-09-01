"""Desktop-owned configuration records with an application replaceable store.

The Desktop process owns its Agent, model, and MCP settings. This module
intentionally exposes a small JSON-backed
reference implementation; another host can implement the same methods against
a database or remote configuration service without changing the v2 kernel.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from sagents.v2.contracts.common import StrictModel, utc_now


def default_agent_config(*, model_provider_id: str = "model_main") -> dict[str, Any]:
    """Return the independent, runnable template for a newly created Agent."""

    return {
        "systemPrefix": "You are a helpful Sage agent.",
        "systemContext": {},
        "agentMode": "simple",
        "subAgentSelectionMode": "auto_all",
        "availableSubAgentIds": [],
        "maxLoopCount": 48,
        "deepThinking": False,
        "thinkingLevel": "medium",
        "llm_provider_id": model_provider_id,
        # Keep the fast-model binding explicit for newly created Agents. Older
        # records without this field remain compatible and fall back to the
        # primary provider at runtime.
        "fast_llm_provider_id": model_provider_id,
        "availableTools": [
            "file_read",
            "grep",
            "glob",
            "list_dir",
            "file_write",
            "file_update",
            "apply_patch",
            "execute_shell_command",
            "await_shell",
            "kill_shell",
            "todo_write",
            "todo_read",
            "turn_status",
            "load_skill",
        ],
        "availableSkills": [],
    }


class DesktopAgentRecord(StrictModel):
    agent_id: str
    user_id: str
    name: str
    is_default: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class DesktopModelCompatibilityProfile(StrictModel):
    """Verified wire contract reused by every runtime provider instance."""

    schema_version: Literal[1, 2] = 2
    route_fingerprint: str = Field(min_length=1)
    verified_at: datetime = Field(default_factory=utc_now)
    max_output_tokens_field: Literal["max_tokens", "max_completion_tokens"] | None = (
        None
    )
    effective_max_output_tokens: int | None = Field(default=None, gt=0)
    reasoning_disable_strategy: Literal[
        "omit",
        "reasoning_effort_none",
        "thinking_type_disabled",
        "enable_thinking_false",
        "thinking_false",
        "chat_template_enable_thinking_false",
    ] = "omit"
    reasoning_behavior: Literal["none", "always", "controllable"] = "none"
    reasoning_effort_strategy: Literal[
        "reasoning_effort", "chat_template_reasoning_effort"
    ] = "reasoning_effort"
    supported_reasoning_efforts: tuple[
        Literal["minimal", "low", "medium", "high", "xhigh", "max"], ...
    ] = ()
    text_only_reasoning_efforts: tuple[
        Literal["minimal", "low", "medium", "high", "xhigh", "max"], ...
    ] = ()
    unsupported_reasoning_efforts: tuple[
        Literal["minimal", "low", "medium", "high", "xhigh", "max"], ...
    ] = ()
    supports_json_object: bool = False
    auxiliary_json_compatible: bool = False
    successful_probes: tuple[str, ...] = ()
    failed_probes: tuple[str, ...] = ()


class DesktopModelProviderRecord(StrictModel):
    id: str
    user_id: str
    name: str
    protocol: Literal[
        "openai-chat-completions", "openai-responses", "anthropic-messages"
    ] = "openai-responses"
    model: str
    base_url: str
    api_key: str = ""
    supports_multimodal: bool = True
    supports_structured_output: bool = True
    supports_tool_calling: bool = True
    is_default: bool = False
    max_tokens: int = Field(default=8192, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    max_model_len: int = Field(default=128_000, gt=0)
    compatibility_profile: DesktopModelCompatibilityProfile | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class DesktopMcpRecord(StrictModel):
    user_id: str
    name: str
    protocol: Literal["stdio", "sse", "streamable_http"]
    disabled: bool = False
    streamable_http_url: str | None = None
    sse_url: str | None = None
    api_key: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    kind: str = "external"
    description: str = ""
    tools: tuple[dict[str, Any], ...] = ()
    simulator: dict[str, Any] = Field(default_factory=dict)


class DesktopCatalogState(StrictModel):
    format_version: Literal["sage.desktop-catalog/v2"] = "sage.desktop-catalog/v2"
    agents: tuple[DesktopAgentRecord, ...] = ()
    model_providers: tuple[DesktopModelProviderRecord, ...] = ()
    mcp_connections: tuple[DesktopMcpRecord, ...] = ()


class DesktopCatalogStore(Protocol):
    async def list_agents(self, user_id: str) -> tuple[DesktopAgentRecord, ...]: ...
    async def get_agent(
        self, agent_id: str, user_id: str
    ) -> DesktopAgentRecord | None: ...
    async def save_agent(self, value: DesktopAgentRecord) -> None: ...
    async def delete_agent(self, agent_id: str, user_id: str) -> None: ...
    async def list_model_providers(
        self, user_id: str
    ) -> tuple[DesktopModelProviderRecord, ...]: ...
    async def get_model_provider(
        self, provider_id: str, user_id: str
    ) -> DesktopModelProviderRecord | None: ...
    async def save_model_provider(self, value: DesktopModelProviderRecord) -> None: ...
    async def delete_model_provider(self, provider_id: str, user_id: str) -> None: ...
    async def list_mcp(self, user_id: str) -> tuple[DesktopMcpRecord, ...]: ...
    async def save_mcp(self, value: DesktopMcpRecord) -> None: ...


class JsonDesktopCatalogStore:
    """Atomic single-host reference store for non-runtime Desktop settings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def initialize_user(self, user_id: str) -> None:
        async with self._lock:
            state = self._read()
            changed = False
            if not any(value.user_id == user_id for value in state.agents):
                state = state.model_copy(
                    update={
                        "agents": (
                            *state.agents,
                            DesktopAgentRecord(
                                agent_id="sage",
                                user_id=user_id,
                                name="Sage",
                                is_default=True,
                                config=default_agent_config(),
                            ),
                        )
                    }
                )
                changed = True
            if not any(value.user_id == user_id for value in state.model_providers):
                state = state.model_copy(
                    update={
                        "model_providers": (
                            *state.model_providers,
                            DesktopModelProviderRecord(
                                id="model_main",
                                user_id=user_id,
                                name="OpenAI",
                                protocol="openai-responses",
                                model="gpt-5.4",
                                base_url="https://api.openai.com/v1",
                                api_key="",
                                is_default=True,
                            ),
                        )
                    }
                )
                changed = True
            if changed:
                self._write(state)

    async def list_agents(self, user_id: str) -> tuple[DesktopAgentRecord, ...]:
        async with self._lock:
            return tuple(
                value for value in self._read().agents if value.user_id == user_id
            )

    async def get_agent(self, agent_id: str, user_id: str) -> DesktopAgentRecord | None:
        async with self._lock:
            return next(
                (
                    value
                    for value in self._read().agents
                    if value.agent_id == agent_id and value.user_id == user_id
                ),
                None,
            )

    async def save_agent(self, value: DesktopAgentRecord) -> None:
        await self._replace("agents", "agent_id", value.agent_id, value.user_id, value)

    async def delete_agent(self, agent_id: str, user_id: str) -> None:
        await self._delete("agents", "agent_id", agent_id, user_id)

    async def list_model_providers(
        self, user_id: str
    ) -> tuple[DesktopModelProviderRecord, ...]:
        async with self._lock:
            return tuple(
                value
                for value in self._read().model_providers
                if value.user_id == user_id
            )

    async def get_model_provider(
        self, provider_id: str, user_id: str
    ) -> DesktopModelProviderRecord | None:
        async with self._lock:
            return next(
                (
                    value
                    for value in self._read().model_providers
                    if value.id == provider_id and value.user_id == user_id
                ),
                None,
            )

    async def save_model_provider(self, value: DesktopModelProviderRecord) -> None:
        await self._replace("model_providers", "id", value.id, value.user_id, value)

    async def delete_model_provider(self, provider_id: str, user_id: str) -> None:
        await self._delete("model_providers", "id", provider_id, user_id)

    async def list_mcp(self, user_id: str) -> tuple[DesktopMcpRecord, ...]:
        async with self._lock:
            return tuple(
                value
                for value in self._read().mcp_connections
                if value.user_id == user_id
            )

    async def save_mcp(self, value: DesktopMcpRecord) -> None:
        await self._replace("mcp_connections", "name", value.name, value.user_id, value)

    async def _replace(
        self, field: str, key: str, identity: str, user_id: str, value
    ) -> None:
        async with self._lock:
            state = self._read()
            values = [
                current
                for current in getattr(state, field)
                if not (
                    getattr(current, key) == identity and current.user_id == user_id
                )
            ]
            values.append(value)
            self._write(state.model_copy(update={field: tuple(values)}))

    async def _delete(self, field: str, key: str, identity: str, user_id: str) -> None:
        async with self._lock:
            state = self._read()
            values = tuple(
                current
                for current in getattr(state, field)
                if not (
                    getattr(current, key) == identity and current.user_id == user_id
                )
            )
            self._write(state.model_copy(update={field: values}))

    def _read(self) -> DesktopCatalogState:
        if not self.path.exists():
            return DesktopCatalogState()
        return DesktopCatalogState.model_validate_json(
            self.path.read_text(encoding="utf-8")
        )

    def _write(self, state: DesktopCatalogState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
