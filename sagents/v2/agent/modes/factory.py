"""Expose first-party Agent modes through the same Flow/Node contracts as users."""

from __future__ import annotations

from dataclasses import dataclass

from sagents.v2.flow.plugins import NativeAgentFlowNode
from sagents.v2.flow import FlowRuntime
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.package.manifest.flows import FlowDefinition, FlowEdge, FlowNode
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor


@dataclass(frozen=True)
class BuiltinModeBundle:
    mode: AgentMode
    flow_id: str
    flow: FlowDefinition
    runtime: FlowRuntime


class BuiltinAgentModeFactory:
    """Simple/Fibre/Team are shipped as ordinary first-party Agent Flow nodes."""

    def __init__(
        self,
        runtime: RuntimePort,
        child_executor: LoopChildRunExecutor,
        *,
        workspace_policy: WorkspaceSharingPolicy = WorkspaceSharingPolicy.SHARED_PARENT,
    ) -> None:
        self.runtime = runtime
        self.child_executor = child_executor
        self.workspace_policy = workspace_policy

    def create(self, descriptor: AgentDescriptor) -> BuiltinModeBundle:
        """Wrap one mode-aware Agent body in an ordinary one-node Flow.

        The outer Flow provides uniform node lifecycle and composition. The
        Agent body still runs as a real child Run, which is why parent and child
        event identities remain separate.
        """

        if descriptor.mode not in {AgentMode.SIMPLE, AgentMode.FIBRE, AgentMode.TEAM}:
            raise ValueError("custom flow mode must use the manifest FlowDefinition")
        flow_id = f"builtin.{descriptor.mode.value}"
        node_id = f"{descriptor.mode.value}.agent"
        flow = FlowDefinition(
            version="2.0.0",
            start=node_id,
            nodes=(FlowNode(id=node_id, type="agent", agent=descriptor.agent_id),),
            edges=(FlowEdge(**{"from": node_id, "to": "end"}),),
        )
        runner = NativeAgentFlowNode(
            runtime=self.runtime,
            descriptor=descriptor,
            child_executor=self.child_executor,
            workspace_policy=self.workspace_policy,
        )
        return BuiltinModeBundle(
            mode=descriptor.mode,
            flow_id=flow_id,
            flow=flow,
            runtime=FlowRuntime(
                runtime=self.runtime,
                flows={flow_id: flow},
                agent_nodes={descriptor.agent_id: runner},
            ),
        )
