import pytest

from app.v2.server.runtime.policy import ExecutionPolicy, intersect_policies
from app.v2.server.packages.tool_policy import server_tool_policy
from sagents.v2.agent.policy import ToolPolicyAction, ToolPolicyContext
from sagents.v2.contracts.principals import ActorRef, PrincipalType
from sagents.v2.tool import SideEffectLevel, ToolCall, ToolDefinition


def context(name="execute_shell_command", level=SideEffectLevel.WRITE):
    return ToolPolicyContext(
        run_id="run", actor=ActorRef(principal_id="user", principal_type=PrincipalType.USER),
        definition=ToolDefinition(name=name, description="test", input_schema={"type": "object"}, side_effect_level=level,
                                  requires_approval=level == SideEffectLevel.WRITE),
        call=ToolCall(tool_call_id="call", tool_name=name, arguments={"command": "ls"},
                      operation_id="operation", idempotency_key="call", owner_run_id="run"),
    )


@pytest.mark.parametrize("shell,expected", [("ask", "require_interaction"),
                                         ("sandboxed", "allow"), ("deny", "deny")])
async def test_shell_policy(shell, expected):
    policy = server_tool_policy(None, execution_policy=ExecutionPolicy(shell=shell))
    assert (await policy.decide(context())).action.value == expected


async def test_unattended_denies_instead_of_waiting_and_does_not_allow_external_tools():
    policy = server_tool_policy(None, execution_policy=ExecutionPolicy(
        shell="sandboxed", on_approval_required="deny"))
    assert (await policy.decide(context("remote_write"))).action == ToolPolicyAction.DENY


async def test_plan_and_scopes_still_override_automatic_shell_execution():
    policy = server_tool_policy(None, execution_policy=ExecutionPolicy(shell="sandboxed"))
    assert (await policy.decide(context().model_copy(update={"invocation_mode": "plan"}))).action == ToolPolicyAction.DENY
    ctx = context()
    ctx = ctx.model_copy(update={"definition": ctx.definition.model_copy(update={"required_scopes": ("process.run",)})})
    assert (await policy.decide(ctx)).action == ToolPolicyAction.DENY


def test_intersection_never_expands_permission():
    effective = intersect_policies(ExecutionPolicy(shell="sandboxed"),
                                  ExecutionPolicy(shell="deny", approval_timeout_seconds=60))
    assert effective.shell == "deny"
    assert effective.approval_timeout_seconds == 60


async def test_live_key_revocation_blocks_even_read_tools():
    async def current():
        return None
    policy = server_tool_policy(None, execution_policy=ExecutionPolicy(shell="sandboxed"),
                               current_policy=current)
    assert (await policy.decide(context("file_read", SideEffectLevel.READ))).action == ToolPolicyAction.DENY
