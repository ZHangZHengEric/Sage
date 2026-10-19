import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.v2.server.runtime.policy import ExecutionPolicy, intersect_policies
from app.v2.server.packages.tool_policy import server_tool_policy
from sagents.v2.agent.policy import ToolPolicyAction, ToolPolicyContext
from sagents.v2.contracts.principals import ActorRef, PrincipalType
from sagents.v2.tool import SideEffectLevel, ToolCall, ToolDefinition


@pytest.mark.parametrize("live_shell", ["sandboxed", "deny", None])
async def test_live_execution_check_uses_only_current_agent_policy(live_shell):
    from app.v2.server.runtime.policy import execution_metadata, live_execution_policy
    from sagents.v2.contracts.commands import StartRun, RunConfig

    frozen = ExecutionPolicy(shell="ask")
    command = StartRun(agent_id="agent", input=(), idempotency_key="start", resolved_spec_hash="sha256:test",
        config=RunConfig(metadata=execution_metadata(frozen, user_id="alice", agent_id="agent")))
    users = SimpleNamespace(get_by_id=AsyncMock(return_value=SimpleNamespace(execution_policy=ExecutionPolicy(shell="sandboxed"))))
    catalog = SimpleNamespace(
        get=AsyncMock(side_effect=AssertionError("must not load full catalog")),
        get_execution_policy=AsyncMock(return_value=ExecutionPolicy(shell=live_shell) if live_shell else None),
    )
    settings = SimpleNamespace(execution_shell_mode="sandboxed", approval_timeout_seconds=86400)
    policy = await live_execution_policy(command, users=users, keys=None, catalog=catalog,
                                         settings=settings, user_id="alice")
    assert (policy.shell if policy else None) == ({"sandboxed": "ask", "deny": "deny", None: None}[live_shell])
    users.get_by_id.assert_awaited_once_with("alice")
    catalog.get_execution_policy.assert_awaited_once_with("alice", "agent")
    users.get_by_id.return_value = None
    assert await live_execution_policy(command, users=users, keys=None, catalog=catalog,
                                        settings=settings, user_id="alice") is None
    assert catalog.get_execution_policy.await_count == 2


async def test_live_execution_reads_user_agent_and_key_concurrently():
    import asyncio
    from app.v2.server.runtime.policy import execution_metadata, live_execution_policy
    from sagents.v2.contracts.commands import StartRun, RunConfig

    arrived = set()
    all_started = asyncio.Event()

    async def read(name, value):
        arrived.add(name)
        if len(arrived) == 3:
            all_started.set()
        await all_started.wait()
        return value

    policy = ExecutionPolicy(shell="sandboxed")
    command = StartRun(agent_id="agent", input=(), idempotency_key="start", resolved_spec_hash="sha256:test",
        config=RunConfig(metadata=execution_metadata(policy, user_id="alice", agent_id="agent", key_id="key")))
    result = await asyncio.wait_for(live_execution_policy(command,
        users=SimpleNamespace(get_by_id=lambda _: read("user", SimpleNamespace(execution_policy=policy))),
        catalog=SimpleNamespace(get_execution_policy=lambda *_: read("agent", policy)),
        keys=SimpleNamespace(get=lambda _: read("key", SimpleNamespace(revoked=False,
            owner_user_id="alice", agent_id="agent", allows=lambda _: True))),
        settings=SimpleNamespace(execution_shell_mode="sandboxed", approval_timeout_seconds=86400),
        user_id="alice"), timeout=1)
    assert result == policy


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


async def test_root_and_member_policy_checks_overlap_and_still_deny_revocation():
    import asyncio
    root_started, member_started = asyncio.Event(), asyncio.Event()

    async def current():
        root_started.set()
        await member_started.wait()
        return ExecutionPolicy(shell="sandboxed")

    async def member(_):
        member_started.set()
        await root_started.wait()
        return None

    policy = server_tool_policy(None, execution_policy=ExecutionPolicy(shell="sandboxed"),
                                current_policy=current, run_policy=member)
    result = await asyncio.wait_for(policy.decide(context()), timeout=1)
    assert result.action == ToolPolicyAction.DENY
