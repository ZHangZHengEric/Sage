"""Durable ownership claims, independent of caller-selected Session IDs."""
from dataclasses import dataclass

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


@dataclass(frozen=True)
class SessionBinding:
    session_id: str
    owner_id: str
    tenant_id: str
    agent_id: str


def require_binding(actual, expected):
    if actual != expected:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.session.ownership_conflict", category=ErrorCategory.CONFLICT,
            message="session_id is already bound to another tenant or Agent",
            metadata={"side_effect_state": "not_applied"},
        ))
