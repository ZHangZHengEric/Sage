from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.server_v2.observability.logging import get_logger
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.protocols import resolve_model_protocol

_LOGGER = get_logger(__name__)


class ModelRecord(BaseModel):
    id: str
    protocol: str = "openai-chat-completions"
    base_url: str = "https://api.openai.com/v1"
    model: str
    api_key: SecretStr
    is_default: bool = True

    def cache_key(self) -> str:
        return "|".join(
            (
                self.id,
                self.protocol,
                self.base_url,
                self.model,
                self.api_key.get_secret_value(),
            )
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
            "is_default": self.is_default,
        }


class AgentRecord(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "model_id": self.model_id or None,
            "tools": list(self.tools),
            "skills": list(self.skills),
        }


SUPPORTED_MCP_PROTOCOLS = ("sse", "streamable_http")


class McpServerRecord(BaseModel):
    """A remote MCP server.

    server_v2 is a public multi-tenant service, so only network transports
    exist here. A ``stdio`` server would run a tenant-supplied command inside
    the server process, which is a remote code execution primitive handed to
    anyone who can register an account.
    """

    name: str
    protocol: Literal["sse", "streamable_http"] = "streamable_http"
    url: str | None = None
    api_key: SecretStr | None = None
    disabled: bool = False
    description: str = ""
    tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_transport(self) -> McpServerRecord:
        """Reject a server that cannot be reached, at the point it is saved.

        The transport was previously only checked while composing a Run, so a
        malformed server was accepted with 200 and then surfaced as an opaque
        runtime failure in the next chat.
        """

        parsed = urlsplit(self.url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{self.protocol} MCP requires an absolute http(s) URL")
        return self

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "protocol": self.protocol,
            "url": self.url,
            "disabled": self.disabled,
            "description": self.description,
            "tools": list(self.tools),
            "has_api_key": self.api_key is not None
            and bool(self.api_key.get_secret_value()),
        }


class A2AAgentRecord(BaseModel):
    """A remote A2A agent this tenant's Agents may delegate work to.

    ``url`` is the peer's base URL rather than its JSON-RPC endpoint: A2A
    publishes the endpoint inside the Agent Card, so pinning it here would make
    the record wrong the moment the peer moved it. The host is still pinned,
    because the host is what the tenant vouched for and what this server sends
    their credential to.
    """

    name: str
    url: str | None = None
    api_key: SecretStr | None = None
    disabled: bool = False
    description: str = ""
    skills: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_endpoint(self) -> A2AAgentRecord:
        parsed = urlsplit(self.url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("A2A agent requires an absolute http(s) URL")
        return self

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "disabled": self.disabled,
            "description": self.description,
            "skills": list(self.skills),
            "has_api_key": self.api_key is not None
            and bool(self.api_key.get_secret_value()),
        }


class UserCatalog(BaseModel):
    agents: list[AgentRecord] = Field(default_factory=list)
    models: list[ModelRecord] = Field(default_factory=list)
    mcp_servers: list[McpServerRecord] = Field(default_factory=list)
    a2a_agents: list[A2AAgentRecord] = Field(default_factory=list)

    @field_validator("a2a_agents", mode="before")
    @classmethod
    def drop_unreachable_peers(cls, value: object) -> object:
        """Ignore persisted peers this deployment cannot call.

        Same reasoning as the MCP validator below: one unusable row costs that
        peer's Tools, while rejecting the record would lock the tenant out of
        every Agent and model too.
        """

        if not isinstance(value, list):
            return value
        kept: list[object] = []
        for item in value:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            try:
                kept.append(A2AAgentRecord.model_validate(item))
            except ValidationError:
                _LOGGER.warning(
                    "catalog.a2a_agent.skipped",
                    "dropping unusable a2a agent",
                    attributes={"name": item.get("name"), "url": item.get("url")},
                )
        return kept

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def drop_unsupported_transports(cls, value: object) -> object:
        """Ignore persisted servers this deployment refuses to run.

        Rows predating the stdio removal — and rows saved before the transport
        was validated at write time — must not make a whole catalog unreadable:
        skipping one obsolete server costs that server's Tools, while rejecting
        the record would lock the tenant out of every Agent and model too.
        """

        if not isinstance(value, list):
            return value
        kept: list[object] = []
        for item in value:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            try:
                kept.append(McpServerRecord.model_validate(item))
            except ValidationError:
                _LOGGER.warning(
                    "catalog.mcp_server.skipped",
                    "dropping unsupported mcp server",
                    attributes={
                        "name": item.get("name"),
                        "protocol": item.get("protocol"),
                    },
                )
        return kept


def empty_catalog() -> UserCatalog:
    return UserCatalog(
        agents=[
            AgentRecord(
                id="main",
                name="Main Assistant",
                instructions="Be helpful, concise, and explicit about uncertainty.",
            )
        ]
    )


def catalog_payload(catalog: UserCatalog) -> dict[str, object]:
    payload = catalog.model_dump(mode="json")
    for item, record in zip(payload.get("models", []), catalog.models):
        item["api_key"] = record.api_key.get_secret_value()
    for item, record in zip(payload.get("mcp_servers", []), catalog.mcp_servers):
        item["api_key"] = (
            record.api_key.get_secret_value() if record.api_key is not None else None
        )
    for item, record in zip(payload.get("a2a_agents", []), catalog.a2a_agents):
        item["api_key"] = (
            record.api_key.get_secret_value() if record.api_key is not None else None
        )
    return payload


def require_agent(catalog: UserCatalog, agent_id: str | None) -> AgentRecord:
    requested = str(agent_id or "").strip()
    if requested:
        match = next((item for item in catalog.agents if item.id == requested), None)
        if match is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.catalog.records.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"unknown agent {requested}",
                )
            )
        return match
    return next(
        (item for item in catalog.agents if item.id == "main"),
        catalog.agents[0] if catalog.agents else empty_catalog().agents[0],
    )


def upsert_agent(
    catalog: UserCatalog, payload: dict[str, object]
) -> tuple[AgentRecord, UserCatalog]:
    agent_id = str(payload.get("id") or "").strip() or new_id("agent")
    if not _AGENT_ID.fullmatch(agent_id):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=f"invalid agent id: {agent_id!r}",
            )
        )
    name = str(payload.get("name") or "").strip()
    if not name:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message="agent name is required",
            )
        )
    existing = next((item for item in catalog.agents if item.id == agent_id), None)
    record = AgentRecord(
        id=agent_id,
        name=name[:191],
        description=str(payload.get("description") or "")[:500],
        instructions=str(payload.get("instructions") or ""),
        model_id=str(payload.get("model_id") or ""),
        tools=_unique_names(payload.get("tools")),
        skills=list(existing.skills)
        if existing is not None
        else _unique_names(payload.get("skills")),
    )
    if record.model_id and not any(
        item.id == record.model_id for item in catalog.models
    ):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=f"unknown model {record.model_id}",
            )
        )
    agents = [item for item in catalog.agents if item.id != agent_id]
    agents.append(record)
    catalog.agents = agents
    return record, catalog


def delete_agent(catalog: UserCatalog, agent_id: str) -> UserCatalog:
    remaining = [item for item in catalog.agents if item.id != agent_id]
    if len(remaining) == len(catalog.agents):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.not_found",
                category=ErrorCategory.VALIDATION,
                message="agent not found",
            )
        )
    if not remaining:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message="at least one agent is required",
            )
        )
    catalog.agents = remaining
    return catalog


def upsert_mcp(
    catalog: UserCatalog, payload: dict[str, object]
) -> tuple[McpServerRecord, UserCatalog]:
    name = str(payload.get("name") or "").strip()
    if not _AGENT_ID.fullmatch(name):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=f"invalid mcp name: {name!r}",
            )
        )
    protocol = str(payload.get("protocol") or "streamable_http").strip()
    if protocol not in SUPPORTED_MCP_PROTOCOLS:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=f"unsupported mcp protocol: {protocol}",
            )
        )
    existing = next((item for item in catalog.mcp_servers if item.name == name), None)
    api_key = str(payload.get("api_key") or "")
    secret = existing.api_key if existing is not None else None
    if api_key:
        secret = SecretStr(api_key)
    tools = payload.get("tools")
    try:
        record = McpServerRecord(
            name=name,
            protocol=protocol,  # type: ignore[arg-type]
            url=str(payload.get("url") or "").strip() or None,
            api_key=secret,
            disabled=bool(payload.get("disabled", False)),
            description=str(payload.get("description") or "")[:500],
            tools=_unique_names(
                tools
                if tools is not None
                else (existing.tools if existing is not None else [])
            ),
        )
    except ValidationError as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=_first_error(exc),
            )
        ) from exc
    servers = [item for item in catalog.mcp_servers if item.name != name]
    servers.append(record)
    catalog.mcp_servers = servers
    return record, catalog


def upsert_a2a_agent(
    catalog: UserCatalog, payload: dict[str, object]
) -> tuple[A2AAgentRecord, UserCatalog]:
    name = str(payload.get("name") or "").strip()
    if not _AGENT_ID.fullmatch(name):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=f"invalid a2a agent name: {name!r}",
            )
        )
    existing = next((item for item in catalog.a2a_agents if item.name == name), None)
    api_key = str(payload.get("api_key") or "")
    secret = existing.api_key if existing is not None else None
    if api_key:
        secret = SecretStr(api_key)
    skills = payload.get("skills")
    try:
        record = A2AAgentRecord(
            name=name,
            url=str(payload.get("url") or "").strip() or None,
            api_key=secret,
            disabled=bool(payload.get("disabled", False)),
            description=str(payload.get("description") or "")[:500],
            skills=_unique_names(
                skills
                if skills is not None
                else (existing.skills if existing is not None else [])
            ),
        )
    except ValidationError as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message=_first_error(exc, "invalid a2a agent"),
            )
        ) from exc
    peers = [item for item in catalog.a2a_agents if item.name != name]
    peers.append(record)
    catalog.a2a_agents = peers
    return record, catalog


def delete_a2a_agent(catalog: UserCatalog, name: str) -> UserCatalog:
    remaining = [item for item in catalog.a2a_agents if item.name != name]
    if len(remaining) == len(catalog.a2a_agents):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.not_found",
                category=ErrorCategory.VALIDATION,
                message="a2a agent not found",
            )
        )
    catalog.a2a_agents = remaining
    return catalog


def enabled_a2a_agents(catalog: UserCatalog) -> list[A2AAgentRecord]:
    return [item for item in catalog.a2a_agents if not item.disabled]


def _first_error(exc: ValidationError, fallback: str = "invalid mcp server") -> str:
    for item in exc.errors():
        message = str(item.get("msg") or "").removeprefix("Value error, ").strip()
        return message or fallback
    return fallback


def delete_mcp(catalog: UserCatalog, name: str) -> UserCatalog:
    remaining = [item for item in catalog.mcp_servers if item.name != name]
    if len(remaining) == len(catalog.mcp_servers):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.not_found",
                category=ErrorCategory.VALIDATION,
                message="mcp server not found",
            )
        )
    catalog.mcp_servers = remaining
    return catalog


def catalog_model(catalog: UserCatalog, model_id: str | None) -> ModelRecord | None:
    if model_id:
        match = next((item for item in catalog.models if item.id == model_id), None)
        if match is not None:
            return match
    return next(
        (item for item in catalog.models if item.is_default),
        catalog.models[0] if catalog.models else None,
    )


def enabled_mcp_servers(catalog: UserCatalog) -> list[McpServerRecord]:
    return [item for item in catalog.mcp_servers if not item.disabled]


_AGENT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:@/-]{0,191}$")


def _unique_names(values) -> list[str]:
    names: list[str] = []
    for value in values or []:
        name = str(value or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def apply_upsert(
    catalog: UserCatalog, payload: dict[str, object]
) -> tuple[ModelRecord, UserCatalog]:
    model_id = str(payload.get("id") or new_id("model"))
    protocol = str(payload.get("protocol") or "openai-chat-completions")
    resolve_model_protocol(protocol)
    record = ModelRecord(
        id=model_id,
        protocol=protocol,
        base_url=str(payload.get("base_url") or "https://api.openai.com/v1"),
        model=str(payload.get("model") or "").strip(),
        api_key=SecretStr(str(payload.get("api_key") or "")),
        is_default=bool(payload.get("is_default", False) or not catalog.models),
    )
    if not record.model:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.validation",
                category=ErrorCategory.VALIDATION,
                message="model is required",
            )
        )
    if not record.api_key.get_secret_value():
        existing = next((item for item in catalog.models if item.id == model_id), None)
        if existing is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.catalog.records.validation",
                    category=ErrorCategory.VALIDATION,
                    message="api_key is required",
                )
            )
        record = record.model_copy(update={"api_key": existing.api_key})
    models = [
        item.model_copy(update={"is_default": False}) if record.is_default else item
        for item in catalog.models
        if item.id != model_id
    ]
    models.append(record)
    catalog.models = models
    return record, catalog


def apply_delete(catalog: UserCatalog, model_id: str) -> UserCatalog:
    remaining = [item for item in catalog.models if item.id != model_id]
    if len(remaining) == len(catalog.models):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.catalog.records.not_found",
                category=ErrorCategory.VALIDATION,
                message="model not found",
            )
        )
    if remaining and not any(item.is_default for item in remaining):
        remaining[0] = remaining[0].model_copy(update={"is_default": True})
    catalog.models = remaining
    return catalog
