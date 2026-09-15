"""Management tools use the package authorizer; other tools retain normal approvals."""

from sagents.v2.agent.policy import (
    DefaultToolPolicy,
    ToolOperationAssessment,
    ToolPolicyAction,
)
from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin


def server_tool_policy(management):
    names = {item.name for item in AgentManagementToolPlugin(management).definitions}

    def assess(context):
        if context.definition.name in names:
            return ToolOperationAssessment(
                action=ToolPolicyAction.ALLOW,
                reason="Package operation is checked by the host authorizer before execution",
            )
        return None

    return DefaultToolPolicy(
        operation_assessor=assess,
        operation_assessor_id="server.package-authorization/v1",
    )
