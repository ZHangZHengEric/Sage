from __future__ import annotations

import re
import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit

from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from sagents.v2.agent.management import AgentPackageBundle
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.v2.server.observability.logging import get_logger
from app.v2.server.runtime.policy import ExecutionPolicy
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.protocols import (
    model_protocol_default_base_url,
    model_protocol_implementation,
    resolve_model_protocol,
)

from sagents.v2.package.manifest.models import (
    ModelRequestDefaults,
    ModelLimits,
    ModelCapabilityDeclaration,
    ModelRoute,
)
from sagents.v2.model.capability_contracts import ModelCapabilityProfile

_LOGGER = get_logger(__name__)


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: ModelRequestDefaults = Field(default_factory=ModelRequestDefaults)
    limits: ModelLimits = Field(default_factory=ModelLimits)
    capabilities: ModelCapabilityDeclaration = Field(
        default_factory=ModelCapabilityDeclaration
    )
    capability_profile: ModelCapabilityProfile | None = None


class ModelRecord(ModelConfiguration):
    id: str
    protocol: str = "openai-chat-completions"
    base_url: str = "https://api.openai.com/v1"
    model: str
    api_key: SecretStr
    is_default: bool = True

    def fingerprint(self) -> str:
        data = [
            self.protocol,
            self.base_url,
            self.model,
            self.api_key.get_secret_value(),
            self.request.model_dump(mode="json"),
            self.limits.model_dump(mode="json"),
        ]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def cache_key(self) -> str:
        return hashlib.sha256(
            self.model_dump_json().encode() + self.api_key.get_secret_value().encode()
        ).hexdigest()

    def current_profile(self):
        profile = self.capability_profile
        implementation = model_protocol_implementation(
            resolve_model_protocol(self.protocol)
        )
        if profile is not None and (
            profile.protocol != resolve_model_protocol(self.protocol).value
            or profile.plugin_id != implementation.plugin_id
            or profile.plugin_version != implementation.plugin_version
        ):
            return None
        return profile

    def route(self) -> ModelRoute:
        return ModelRoute(
            provider=resolve_model_protocol(self.protocol).value,
            base_url=self.base_url,
            model=self.model,
            **self.model_dump(include={"request", "limits", "capabilities"}),
            capability_profile=self.current_profile(),
        )

    def public_dict(self) -> dict[str, object]:
        data = self.model_dump(mode="json", exclude={"api_key"})
        if self.current_profile() is None:
            data["capability_profile"] = None
        return data


def _default_agent_tools():
    from app.v2.server.runtime.official import default_agent_tools
    return default_agent_tools()


class AgentRecord(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    model_id: str = ""
    tools: list[str] = Field(default_factory=_default_agent_tools)
    external_tools: list[str] = Field(default_factory=list)
    tool_approval: ToolApprovalConfig | None = None
    skills: list[str] = Field(default_factory=list)
    # A ceiling, not a grant: API Keys still default to asking for approval.
    execution_policy: ExecutionPolicy = Field(default_factory=lambda: ExecutionPolicy(shell="sandboxed"))

    package: AgentPackageBundle | None = None

    @model_validator(mode="after")
    def canonical_package(self):
        from app.v2.server.catalog.packages import build_package, project_package
        if self.package is None:
            self.package = build_package(self)
        return project_package(self)

    @property
    def fast_model_id(self):
        definition = self.package.manifest.agents[self.id]
        model_id = definition.models.get("fast", "")
        return model_id if model_id != "default" else ""

    @property
    def sandbox(self):
        return self.package.manifest.agents[self.id].sandbox

    def with_configuration(self, **updates):
        from app.v2.server.catalog.packages import build_package
        sandbox = updates.pop("sandbox", None)
        projection = self.model_copy(update=updates)
        projection.execution_policy = ExecutionPolicy.model_validate(projection.execution_policy)
        if projection.tool_approval is not None:
            projection.tool_approval = ToolApprovalConfig.model_validate(projection.tool_approval)
        projection.package = build_package(projection, sandbox=sandbox, previous=self.package)
        return AgentRecord.model_validate(projection.model_dump(mode="json"))

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "package": self.package.model_dump(mode="json"),
            "package_ref": self.package.content_hash,
            "sandbox": self.sandbox.model_dump(mode="json"),
            "description": self.description,
            "instructions": self.instructions,
            "model_id": self.model_id or None,
            "fast_model_id": self.fast_model_id or None,
            "tools": list(self.tools),
            "external_tools": self.external_tools,
            "skills": list(self.skills),
            "tool_approval": self.tool_approval.model_dump() if self.tool_approval else None,
            "execution_policy": self.execution_policy.model_dump(),
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
    timeout_seconds: float = Field(default=30, gt=0, le=900)

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
            "timeout_seconds": self.timeout_seconds,
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
    default_agent_id: str = ""
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
    agent = AgentRecord(
        id=new_id("agent"),
        name="Main Assistant",
        instructions="Be helpful, concise, and explicit about uncertainty.",
    )
    return UserCatalog(default_agent_id=agent.id, agents=[agent])


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
    requested = str(agent_id or catalog.default_agent_id or "").strip()
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
    raise SageV2Error(
        RuntimeErrorInfo(
            code="server.catalog.records.not_found",
            category=ErrorCategory.VALIDATION,
            message="default agent is not configured",
        )
    )


def upsert_agent(
    catalog: UserCatalog, payload: dict[str, object], *, registry=None
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
        tools=_unique_names(payload.get("tools", existing.tools if existing else _default_agent_tools())),
        external_tools=_unique_names(payload.get("external_tools", existing.external_tools if existing else [])),
        tool_approval=payload.get("tool_approval", existing.tool_approval if existing else None),
        execution_policy=ExecutionPolicy.model_validate(payload.get("execution_policy") or
            (existing.execution_policy.model_dump() if existing else {"shell": "sandboxed"})),
        skills=list(existing.skills)
        if existing is not None
        else _unique_names(payload.get("skills")),
    )
    if existing is not None:
        record = existing.with_configuration(**record.model_dump(exclude={"id", "package"}),
                                             sandbox=payload.get("sandbox"))
    elif payload.get("sandbox") is not None:
        record = record.with_configuration(sandbox=payload["sandbox"])
    if "fast_model_id" in payload:
        fast_id = str(payload.get("fast_model_id") or "")
        if fast_id and not any(item.id == fast_id for item in catalog.models):
            raise SageV2Error(RuntimeErrorInfo(code="server.catalog.validation",
                category=ErrorCategory.VALIDATION, message=f"unknown fast model {fast_id}"))
        data = record.package.model_dump(mode="json")
        definition = data["manifest"]["agents"][record.id]
        if fast_id:
            definition["models"]["fast"] = fast_id
        else:
            definition["models"].pop("fast", None)
        record = record.model_copy(update={"package": AgentPackageBundle.model_validate(data)}).with_configuration()
    advanced = {
        key: payload[key] for key in ("budgets", "memory") if payload.get(key) is not None
    }
    if advanced:
        data = record.package.model_dump(mode="json")
        data["manifest"]["agents"][record.id].update(advanced)
        record = record.model_copy(
            update={"package": AgentPackageBundle.model_validate(data)}
        )
        # Recompute the content version after updating canonical fields.
        record = record.with_configuration()
    if payload.get("plugins") is not None:
        from app.v2.server.catalog.plugins import validate_agent_plugins, AGENT_DEFAULTS

        validate_agent_plugins(payload["plugins"], registry=registry)
        data = record.package.model_dump(mode="json")
        current = data["manifest"]["runtime"].get("capabilities", {})
        data["manifest"]["runtime"]["capabilities"] = {
            k: v for k, v in current.items() if k not in AGENT_DEFAULTS
        } | payload["plugins"]
        record = record.model_copy(
            update={"package": AgentPackageBundle.model_validate(data)}
        ).with_configuration()
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
    if catalog.default_agent_id == agent_id:
        catalog.default_agent_id = remaining[0].id
    return catalog


def upsert_mcp(
    catalog: UserCatalog, payload: dict[str, object], *, registry=None
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
            timeout_seconds=(payload.get("timeout_seconds") if payload.get("timeout_seconds") is not None
                else (existing.timeout_seconds if existing is not None else 30)),
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
    catalog: UserCatalog, payload: dict[str, object], *, registry=None
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
    catalog: UserCatalog, payload: dict[str, object], *, registry=None
) -> tuple[ModelRecord, UserCatalog]:
    model_id = str(payload.get("id") or new_id("model"))
    protocol = str(payload.get("protocol") or "openai-chat-completions")
    resolve_model_protocol(protocol)
    existing = next((item for item in catalog.models if item.id == model_id), None)
    record = ModelRecord(
        **{key: payload.get(key, getattr(existing, key) if existing else field.get_default(call_default_factory=True))
           for key, field in ModelConfiguration.model_fields.items()},
        id=model_id,
        protocol=protocol,
        base_url=str(
            payload.get("base_url") or model_protocol_default_base_url(protocol)
        ),
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
    if record.capability_profile and record.capability_profile.route_fingerprint != record.fingerprint():
        record = record.model_copy(update={"capability_profile": None})
    try:
        record.route()  # Validate endpoints and route configuration before persistence.
    except ValueError as exc:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.catalog.records.validation", category=ErrorCategory.VALIDATION,
            message=str(exc),
        )) from exc
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
