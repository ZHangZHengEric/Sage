"""Project optional provider-owned environment descriptions into model context."""

from __future__ import annotations

import inspect
import json

from sagents.v2.context.contracts import ContextSegment, ContextStability


class SandboxEnvironmentContextProvider:
    def __init__(self, sandbox):
        self.sandbox = sandbox

    async def segments(self, command, *, run_id=None):
        describe = getattr(self.sandbox, "describe_environment", None)
        if not callable(describe):
            return ()
        environment = describe()
        if inspect.isawaitable(environment):
            environment = await environment
        if not environment:
            return ()
        return (
            ContextSegment(
                segment_id="sandbox_environment",
                content="<sandbox_environment>\n"
                + json.dumps(environment, ensure_ascii=False, indent=2)
                + "\n</sandbox_environment>",
                stability=ContextStability.STABLE,
                priority=90,
                sensitive=True,
            ),
        )
