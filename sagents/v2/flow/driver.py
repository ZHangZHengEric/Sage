"""Adapt a versioned FlowRuntime to the standard SAgent driver interface."""

from __future__ import annotations


class AgentFlowDriver:
    def __init__(self, runtime, flow_id, child_executor):
        self.flow_runtime = runtime
        self.flow_id = flow_id
        self.child_executor = child_executor

    async def execute(self, run_id, context):
        return await self.flow_runtime.execute(run_id, self.flow_id, context)

    async def resume(self, run_id, context):
        return await self.flow_runtime.resume(run_id, context)

    async def close(self):
        await self.child_executor.close()
