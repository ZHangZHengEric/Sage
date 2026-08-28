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

__all__ = [
    "AgentDescriptor",
    "AgentInvocationMode",
    "AgentMode",
    "AgentRegistry",
    "DelegationBatch",
    "DelegationResult",
    "DelegationTask",
    "MultiAgentCoordinator",
    "WorkspaceSharingPolicy",
]
