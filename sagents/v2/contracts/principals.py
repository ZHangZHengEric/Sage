"""SAgents V2 module for contracts/principals.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class PrincipalType(str, Enum):
    USER = "user"
    SERVICE = "service"
    AGENT = "agent"
    WORKER = "worker"


class ActorRef(StrictModel):
    principal_id: Identifier
    principal_type: PrincipalType
    tenant_id: Identifier | None = None
    delegated_by: Identifier | None = None
    scopes: tuple[str, ...] = ()


class TraceContext(StrictModel):
    trace_id: Identifier | None = None
    span_id: Identifier | None = None
    correlation_id: Identifier | None = None


class RequestContext(StrictModel):
    actor: ActorRef
    trace: TraceContext = Field(default_factory=TraceContext)
    deadline: datetime | None = None
