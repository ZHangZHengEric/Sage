"""Agent-loop public facade with lazy implementation exports."""

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

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
