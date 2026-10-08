"""Management tools use the package authorizer; other tools retain normal approvals."""

from sagents.v2.agent.policy import (
    DefaultToolPolicy,
    ToolOperationAssessment,
    ToolPolicyAction,
)
from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin
from app.v2.server.runtime.policy import ExecutionPolicy, intersect_policies


def server_tool_policy(management, *, execution_policy=None, current_policy=None, machine_invocation=False):
    names = {item.name for item in AgentManagementToolPlugin(management).definitions} if management is not None else set()
    configured = execution_policy or ExecutionPolicy()

    def assess(context):
        if configured.shell == "sandboxed" and context.definition.name in {
            "file_write", "file_update", "apply_patch", "kill_shell",
        }:
            return ToolOperationAssessment(action=ToolPolicyAction.ALLOW,
                reason="Workspace operations are authorized within the sandbox")
        if context.definition.name == "execute_shell_command":
            return ToolOperationAssessment(
                action={"ask": ToolPolicyAction.REQUIRE_INTERACTION,
                        "sandboxed": ToolPolicyAction.ALLOW,
                        "deny": ToolPolicyAction.DENY}[configured.shell],
                reason={"ask": "Shell execution requires approval",
                        "sandboxed": "Shell execution is authorized within the workspace sandbox",
                        "deny": "Shell execution is disabled by the execution grant"}[configured.shell],
                category="server_shell_execution",
            )
        if context.definition.name in names:
            if machine_invocation or context.actor.delegated_by:
                return ToolOperationAssessment(action=ToolPolicyAction.DENY,
                    reason="Machine credentials cannot manage Agent packages")
            return ToolOperationAssessment(
                action=ToolPolicyAction.ALLOW,
                reason="Package operation is checked by the host authorizer before execution",
            )
        return None

    class ServerToolPolicy(DefaultToolPolicy):
        async def decide(self, context):
            effective = configured
            if current_policy is not None:
                live = await current_policy()
                if live is None:
                    decision = await super().decide(context)
                    return decision.model_copy(update={"action": ToolPolicyAction.DENY,
                        "reason": "The originating execution credential was revoked or removed",
                        "allowed_decisions": (), "interaction_payload": {}})
                effective = intersect_policies(configured, live)
            # Rebuild with the complete effective configuration in the audit hash.
            policy = server_tool_policy(management, execution_policy=effective,
                machine_invocation=machine_invocation) if effective != configured else self
            decision = await DefaultToolPolicy.decide(policy, context)
            if decision.action == ToolPolicyAction.REQUIRE_INTERACTION and effective.on_approval_required == "deny":
                return decision.model_copy(update={"action": ToolPolicyAction.DENY,
                    "reason": "This execution grant rejects operations requiring approval",
                    "allowed_decisions": (), "interaction_payload": {}})
            return decision

    return ServerToolPolicy(operation_assessor=assess,
        operation_assessor_id=f"server.execution-policy/v1:{configured.fingerprint}:machine={machine_invocation}")
