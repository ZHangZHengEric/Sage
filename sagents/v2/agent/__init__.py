"""Agent-loop public facade with lazy implementation exports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.agent.factory import AgentCompositionFactory as AgentCompositionFactory
    from sagents.v2.agent.state import AgentLoopCheckpointState as AgentLoopCheckpointState
    from sagents.v2.agent.engine import AgentLoopEngine as AgentLoopEngine
    from sagents.v2.agent.step_request import AgentStepRequestBuilder as AgentStepRequestBuilder
    from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder as DefaultAgentStepRequestBuilder
    from sagents.v2.agent.observed import ObservedRunDriver as ObservedRunDriver
    from sagents.v2.agent.step_request import PreparedAgentStep as PreparedAgentStep


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "AgentCompositionFactory": ("sagents.v2.agent.factory", "AgentCompositionFactory"),
    "AgentLoopCheckpointState": ("sagents.v2.agent.state", "AgentLoopCheckpointState"),
    "AgentLoopEngine": ("sagents.v2.agent.engine", "AgentLoopEngine"),
    "AgentStepRequestBuilder": (
        "sagents.v2.agent.step_request",
        "AgentStepRequestBuilder",
    ),
    "DefaultAgentStepRequestBuilder": (
        "sagents.v2.agent.step_request",
        "DefaultAgentStepRequestBuilder",
    ),
    "ObservedRunDriver": ("sagents.v2.agent.observed", "ObservedRunDriver"),
    "PreparedAgentStep": ("sagents.v2.agent.step_request", "PreparedAgentStep"),
}

__all__ = [
    "AgentCompositionFactory",
    "AgentLoopCheckpointState",
    "AgentLoopEngine",
    "AgentStepRequestBuilder",
    "DefaultAgentStepRequestBuilder",
    "ObservedRunDriver",
    "PreparedAgentStep",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
