"""SAgents V2 module for agent/multi_agent/executors/__init__.py."""

from sagents.v2.agent.multi_agent.executors.loop import (
    ChildRunConfigResolver,
    LoopChildRunExecutor,
)

__all__ = ["ChildRunConfigResolver", "LoopChildRunExecutor"]
