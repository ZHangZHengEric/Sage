import pytest

from app.v2.server.packages.tool_policy import server_tool_policy
from app.v2.server.runtime.policy import ExecutionPolicy
from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from sagents.v2.agent.policy import (
    DefaultToolPolicy,
    ToolOperationAssessment,
    ToolPolicyAction,
)
from sagents.v2.tool.plugins.mcp import McpToolPlugin
from tests.app.v2.server.test_execution_policy import context
from tests.app.v2.server.conftest import register_and_login


@pytest.mark.parametrize(
    "name,key", [("file_write", None), ("mcp_drive_write", "mcp:drive:write")]
)
@pytest.mark.parametrize(
    "default,rule,expected",
    [
        ("auto_approve", "inherit", "allow"),
        ("auto_approve", "ask", "require_interaction"),
        ("ask", "auto_approve", "allow"),
        ("ask", "inherit", "require_interaction"),
    ],
)
async def test_agent_rules_override_risk_and_legacy_allow_lists(
    name, key, default, rule, expected
):
    ctx = context(name)
    ctx = ctx.model_copy(
        update={"definition": ctx.definition.model_copy(update={"approval_key": key})}
    )
    policy = server_tool_policy(
        None, execution_policy=ExecutionPolicy(shell="sandboxed")
    ).with_approval_config(
        ToolApprovalConfig(default=default, tools={key or name: rule})
    )
    assert (await policy.decide(ctx)).action.value == expected


@pytest.mark.parametrize(
    "constraint", ["scope", "plan", "shell", "revoked", "assessor", "shell_ask"]
)
async def test_auto_approval_cannot_override_execution_constraints(constraint):
    ctx = context()

    async def revoked():
        return None

    policy = server_tool_policy(
        None,
        execution_policy=ExecutionPolicy(
            shell="deny"
            if constraint == "shell"
            else "ask"
            if constraint == "shell_ask"
            else "sandboxed"
        ),
        current_policy=revoked if constraint == "revoked" else None,
    )
    if constraint == "scope":
        ctx = ctx.model_copy(
            update={
                "definition": ctx.definition.model_copy(
                    update={"required_scopes": ("missing",)}
                )
            }
        )
    if constraint == "plan":
        ctx = ctx.model_copy(update={"invocation_mode": "plan"})
    if constraint == "assessor":
        policy = DefaultToolPolicy(
            operation_assessor=lambda _: ToolOperationAssessment(
                action=ToolPolicyAction.DENY, reason="account policy denied"
            )
        )
    policy = policy.with_approval_config(ToolApprovalConfig())
    expected = (
        ToolPolicyAction.REQUIRE_INTERACTION
        if constraint == "shell_ask"
        else ToolPolicyAction.DENY
    )
    assert (await policy.decide(ctx)).action == expected


async def test_live_policy_rebuild_preserves_agent_approval_rules():
    async def live():
        return ExecutionPolicy(shell="sandboxed", approval_timeout_seconds=60)

    policy = server_tool_policy(
        None, execution_policy=ExecutionPolicy(shell="sandboxed"), current_policy=live
    )
    policy = policy.with_approval_config(ToolApprovalConfig(default="ask"))
    assert (
        await policy.decide(context("file_read"))
    ).action == ToolPolicyAction.REQUIRE_INTERACTION


def test_mcp_approval_identity_does_not_merge_same_names_or_normalized_names():
    assert McpToolPlugin.approval_key("one", "write") != McpToolPlugin.approval_key(
        "two", "write"
    )
    assert McpToolPlugin.approval_key("one-two", "write") != McpToolPlugin.approval_key(
        "one_two", "write"
    )
    assert McpToolPlugin.approval_key("a:b", "c") != McpToolPlugin.approval_key(
        "a", "b:c"
    )


def test_api_and_package_round_trip_approval_rules(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    rules = {
        "default": "auto_approve",
        "tools": {
            "file_write": "ask",
            "mcp:one:write": "ask",
            "mcp:two:write": "inherit",
        },
    }
    created = client.post(
        "/api/agents",
        headers=headers,
        json={"name": "Approval rules", "tool_approval": rules},
    )
    assert created.status_code == 200, created.text
    agent = created.json()["data"]
    assert agent["tool_approval"] == rules
    bundle = client.get(
        f"/api/agent-packages/template?agent_id={agent['id']}", headers=headers
    ).json()["data"]
    assert bundle["manifest"]["agents"]["assistant"]["tool_approval"] == rules
    imported = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert imported.status_code == 200, imported.text
    ref = imported.json()["data"]["ref"]
    exported = client.get(f"/api/agent-packages/{ref}", headers=headers).json()["data"]
    assert exported == bundle
    restored = client.post(
        f"/api/agent-packages/{ref}/activate", headers=headers, json={}
    )
    assert restored.status_code == 200, restored.text
    exported = client.get(f"/api/agent-packages/{ref}", headers=headers).json()["data"]
    assert exported["manifest"]["agents"]["assistant"]["tool_approval"] == rules
    invalid = client.put(
        f"/api/agents/{agent['id']}",
        headers=headers,
        json={"name": "Bad", "tool_approval": {"default": "allow_everything"}},
    )
    assert invalid.status_code == 422


def test_updates_from_legacy_clients_preserve_rules_and_explicit_null_clears_them(
    client,
):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    rules = {"default": "ask", "tools": {"file_read": "auto_approve"}}
    created = client.post(
        "/api/agents",
        headers=headers,
        json={"name": "Configured", "tool_approval": rules},
    ).json()["data"]
    response = client.put(
        f"/api/agents/{created['id']}", headers=headers, json={"name": "Renamed"}
    )
    assert response.json()["data"]["tool_approval"] == rules
    response = client.put(
        f"/api/agents/{created['id']}",
        headers=headers,
        json={"name": "Legacy", "tool_approval": None},
    )
    assert response.json()["data"]["tool_approval"] is None


def test_policy_hash_tracks_final_approval_rules():
    one = ToolApprovalConfig(default="ask")
    two = ToolApprovalConfig(default="auto_approve", tools={"file_read": "ask"})
    base = DefaultToolPolicy()
    assert (
        base.with_approval_config(one).policy_hash
        != base.with_approval_config(two).policy_hash
    )
    assert (
        base.with_approval_config(one).with_approval_config(two).policy_hash
        == DefaultToolPolicy(tool_approval=two).policy_hash
    )
    assert base.tool_approval is None


def test_tool_catalog_exposes_stable_mcp_approval_ids(client, service, monkeypatch):
    from contextlib import asynccontextmanager
    from sagents.v2.tool.plugins.mcp import McpServerConfig
    from tests.sagents.v2.test_mcp_tool_bridge_matrix import FakeSession

    @asynccontextmanager
    async def factory(_):
        yield FakeSession()

    plugin = McpToolPlugin(
        (
            McpServerConfig(
                name="drive", protocol="streamable_http", url="https://mcp.test"
            ),
        ),
        session_factory=factory,
    )
    monkeypatch.setattr(service.catalog.mcp_plugins, "get", lambda *_: plugin)
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    response = client.get("/api/tools", headers=headers)
    assert response.status_code == 200, response.text
    tool = next(
        t for t in response.json()["data"] if t["name"] == "mcp_drive_search_files"
    )
    assert tool["approval_key"] == "mcp:drive:search%20files"
