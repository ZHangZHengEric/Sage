"""Model-facing Tool result processing port, after execution and reconciliation."""

from typing import Protocol

from sagents.v2.contracts.principals import RequestContext
from sagents.v2.tool.contracts import ToolCall, ToolExecutionResult


class ToolResultProcessor(Protocol):
    async def process(
        self, result: ToolExecutionResult, *, call: ToolCall,
        context: RequestContext, runtime=None,
    ) -> ToolExecutionResult: ...
