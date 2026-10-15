"""Resolve per-Run system context without mutating the admitted command."""

from collections.abc import Mapping

from sagents.v2.contracts.commands import StartRun


def with_session_context(command: StartRun, session_id: str) -> StartRun:
    configured = command.config.metadata.get("system_context")
    system_context = dict(configured) if isinstance(configured, Mapping) else {}
    # The durable Run identity is authoritative, including forks and legacy Runs.
    system_context["session_id"] = session_id
    return command.model_copy(update={"config": command.config.model_copy(update={
        "metadata": {**command.config.metadata, "system_context": system_context},
    })})
