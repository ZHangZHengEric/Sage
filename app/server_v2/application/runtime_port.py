"""Narrow view of the process SAgentApplication."""

from __future__ import annotations


class AgentRuntime:
    def __init__(self, application) -> None:
        self._application = application

    def _app(self):
        app = self._application()
        if app is None:
            raise RuntimeError("Server v2 runtime is not started")
        return app

    @property
    def composition_hash(self):
        return self._app().composition_hash

    def entrypoint(self):
        return self._app().entrypoint()

    async def open_run(self, interface: str, command, context):
        app = self._app()
        return await app.run_interface(
            interface,
            command,
            context,
            agent_id=app.resolved_plan.entrypoint_agent_id,
        )
