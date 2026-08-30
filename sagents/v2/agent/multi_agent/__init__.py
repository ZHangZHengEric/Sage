"""SAgents V2 module for agent/multi_agent/__init__.py."""

from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    AgentInvocationMode,
    AgentMode,
    DelegationBatch,
    DelegationResult,
    DelegationTask,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.coordinator import MultiAgentCoordinator
from sagents.v2.agent.multi_agent.registry import AgentRegistry
from sagents.v2.agent.multi_agent.context import AgentRosterContextProvider
from sagents.v2.agent.multi_agent.session_roster import SessionDynamicAgentRoster

__all__ = [
    "AgentDescriptor",
    "AgentInvocationMode",
    "AgentMode",
    "AgentRegistry",
    "AgentRosterContextProvider",
    "DelegationBatch",
    "DelegationResult",
    "DelegationTask",
    "MultiAgentCoordinator",
    "SessionDynamicAgentRoster",
    "WorkspaceSharingPolicy",
]
