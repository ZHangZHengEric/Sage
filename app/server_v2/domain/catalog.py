from __future__ import annotations

import re

from pydantic import BaseModel, Field, SecretStr
from sagents.v2.contracts.common import new_id
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    resolve_model_protocol,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.credentials.contracts import CredentialMaterial

from app.server_v2.core.errors import ServerV2Error


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

    def to_provider(self) -> ModelProvider:
        route = ModelRoute(
            provider=resolve_model_protocol(self.protocol).value,
            base_url=self.base_url,
            model=self.model,
        )
        credential = CredentialMaterial(
            credential_id=f"catalog-{self.id}",
            secret=self.api_key,
            source="host",
        )
        return create_registered_model_provider(route, credential)


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


class McpServerRecord(BaseModel):
    name: str
    protocol: str = "stdio"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    api_key: SecretStr | None = None
    disabled: bool = False
    description: str = ""
    tools: list[str] = Field(default_factory=list)

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "protocol": self.protocol,
            "url": self.url,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "disabled": self.disabled,
            "description": self.description,
            "tools": list(self.tools),
            "has_api_key": self.api_key is not None
            and bool(self.api_key.get_secret_value()),
        }


class UserCatalog(BaseModel):
    agents: list[AgentRecord] = Field(default_factory=list)
    models: list[ModelRecord] = Field(default_factory=list)
    mcp_servers: list[McpServerRecord] = Field(default_factory=list)


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
    return payload


def require_agent(catalog: UserCatalog, agent_id: str | None) -> AgentRecord:
    requested = str(agent_id or "").strip()
    if requested:
        match = next((item for item in catalog.agents if item.id == requested), None)
        if match is None:
            raise ServerV2Error("not_found", f"unknown agent {requested}")
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
        raise ServerV2Error("validation", f"invalid agent id: {agent_id!r}")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ServerV2Error("validation", "agent name is required")
    existing = next((item for item in catalog.agents if item.id == agent_id), None)
    record = AgentRecord(
        id=agent_id,
        name=name[:191],
        description=str(payload.get("description") or "")[:500],
        instructions=str(payload.get("instructions") or ""),
        model_id=str(payload.get("model_id") or ""),
        tools=_unique_names(payload.get("tools")),
        skills=list(existing.skills) if existing is not None else _unique_names(
            payload.get("skills")
        ),
    )
    if record.model_id and not any(item.id == record.model_id for item in catalog.models):
        raise ServerV2Error("validation", f"unknown model {record.model_id}")
    agents = [item for item in catalog.agents if item.id != agent_id]
    agents.append(record)
    catalog.agents = agents
    return record, catalog


def delete_agent(catalog: UserCatalog, agent_id: str) -> UserCatalog:
    remaining = [item for item in catalog.agents if item.id != agent_id]
    if len(remaining) == len(catalog.agents):
        raise ServerV2Error("not_found", "agent not found")
    if not remaining:
        raise ServerV2Error("validation", "at least one agent is required")
    catalog.agents = remaining
    return catalog


def upsert_mcp(
    catalog: UserCatalog, payload: dict[str, object]
) -> tuple[McpServerRecord, UserCatalog]:
    name = str(payload.get("name") or "").strip()
    if not _AGENT_ID.fullmatch(name):
        raise ServerV2Error("validation", f"invalid mcp name: {name!r}")
    protocol = str(payload.get("protocol") or "stdio").strip()
    if protocol not in {"stdio", "sse", "streamable_http"}:
        raise ServerV2Error("validation", f"unsupported mcp protocol: {protocol}")
    existing = next((item for item in catalog.mcp_servers if item.name == name), None)
    api_key = str(payload.get("api_key") or "")
    secret = existing.api_key if existing is not None else None
    if api_key:
        secret = SecretStr(api_key)
    record = McpServerRecord(
        name=name,
        protocol=protocol,
        url=str(payload.get("url") or "") or None,
        command=str(payload.get("command") or "") or None,
        args=[str(item) for item in payload.get("args") or [] if str(item).strip()],
        env={
            str(key): str(value)
            for key, value in dict(payload.get("env") or {}).items()
            if str(key).strip()
        },
        api_key=secret,
        disabled=bool(payload.get("disabled", False)),
        description=str(payload.get("description") or "")[:500],
        tools=_unique_names(payload.get("tools") if payload.get("tools") is not None else (
            existing.tools if existing is not None else []
        )),
    )
    servers = [item for item in catalog.mcp_servers if item.name != name]
    servers.append(record)
    catalog.mcp_servers = servers
    return record, catalog


def delete_mcp(catalog: UserCatalog, name: str) -> UserCatalog:
    remaining = [item for item in catalog.mcp_servers if item.name != name]
    if len(remaining) == len(catalog.mcp_servers):
        raise ServerV2Error("not_found", "mcp server not found")
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
        raise ServerV2Error("validation", "model is required")
    if not record.api_key.get_secret_value():
        existing = next((item for item in catalog.models if item.id == model_id), None)
        if existing is None:
            raise ServerV2Error("validation", "api_key is required")
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
        raise ServerV2Error("not_found", "model not found")
    if remaining and not any(item.is_default for item in remaining):
        remaining[0] = remaining[0].model_copy(update={"is_default": True})
    catalog.models = remaining
    return catalog
