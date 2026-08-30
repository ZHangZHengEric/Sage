"""SAgents V2 module for flow/plugins/agent.py."""

from __future__ import annotations

import json

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.flow import FlowNodeContext, FlowNodeOutcome, FlowNodeResult
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    AgentInvocationMode,
    DelegationTask,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor


class NativeAgentFlowNode:
    """First-party Flow node whose body is the standard message/model/tool loop."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        descriptor: AgentDescriptor,
        child_executor: LoopChildRunExecutor,
        workspace_policy: WorkspaceSharingPolicy = WorkspaceSharingPolicy.SHARED_PARENT,
    ) -> None:
        self.runtime = runtime
        self.descriptor = descriptor
        self.child_executor = child_executor
        self.workspace_policy = workspace_policy

    async def run(self, context: FlowNodeContext) -> FlowNodeResult:
        command = await self.runtime.session_store.get_start_command(context.run_id)
        task_content = context.config.get("content") or self._input_text(command.input)
        result = await self.child_executor.run_child(
            self.descriptor,
            DelegationTask(
                task_id=f"{context.flow_execution_id}:{context.node_execution_id}",
                agent_id=self.descriptor.agent_id,
                task_name=str(context.config.get("task_name") or context.node_id),
                original_task=self._input_text(command.input),
                content=task_content,
                flow_boundary=str(
                    context.config.get("flow_boundary") or "complete_node"
                ),
                invocation_mode=AgentInvocationMode.AGENT_AS_TOOL,
            ),
            parent_run_id=context.run_id,
            workspace_policy=self.workspace_policy,
            context=context.request_context,
        )
        output = {
            "agent_id": result.agent_id,
            "child_run_id": result.child_run_id,
            "child_session_id": result.child_session_id,
            "outcome": result.outcome.value,
            "content": [value.model_dump(mode="json") for value in result.content],
        }
        if result.outcome != RunState.COMPLETED:
            return FlowNodeResult(
                outcome=(
                    FlowNodeOutcome.SUSPENDED
                    if result.outcome == RunState.SUSPENDED
                    else FlowNodeOutcome.FAILED
                ),
                output=output,
                error=result.error
                or RuntimeErrorInfo(
                    code="agent.node_failed",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=f"agent node ended in {result.outcome.value}",
                    safe_to_resume=result.outcome == RunState.SUSPENDED,
                ),
            )
        return FlowNodeResult(output=output)

    @staticmethod
    def _input_text(items) -> str:
        values = []
        for item in items:
            for block in item.content:
                if isinstance(block, TextBlock):
                    values.append(block.text)
                elif isinstance(block, JsonBlock):
                    values.append(json.dumps(block.value, ensure_ascii=False))
        return "\n".join(values)
