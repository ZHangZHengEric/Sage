"""Run tool composition keeps ownership with execution drivers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sagents.v2.composition.bound_tools import BoundToolComposer
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime


def composer(open_tools):
    return BoundToolComposer(
        open_tools=open_tools,
        workspace_initializer=object(),
        artifact_store=object(),
        job_runtime=InMemoryJobRuntime({}),
        memory_services={"member": object()},
        default_memory_service=object(),
        session_memory_service=object(),
        goal_state_service=object(),
        tool_selection=object(),
    )


def binding(run_id):
    return SimpleNamespace(
        run_id=run_id,
        sandbox=SimpleNamespace(ref=SimpleNamespace(owner_run_id=run_id)),
        grant_issuer=object(),
        initialize_workspace=AsyncMock(),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_bound_tools_are_run_scoped_and_share_only_selected_services():
    opener = AsyncMock(
        side_effect=[(object(), object(), object()), (object(), object(), object())]
    )
    wiring = composer(opener)
    root, child = binding("root"), binding("child")
    root_tools = await wiring.compose(root, tenant_id="t", agent_id="root-agent")
    child_tools = await wiring.compose(child, tenant_id="t", agent_id="member")
    assert root_tools.runtime is not child_tools.runtime
    assert root_tools.runtime.sandbox is root.sandbox
    assert child_tools.runtime.sandbox is child.sandbox
    assert root_tools.runtime.memory_service is wiring.default_memory_service
    assert child_tools.runtime.memory_service is wiring.memory_services["member"]
    assert (
        root_tools.runtime.job_runtime
        is child_tools.runtime.job_runtime
        is wiring.job_runtime
    )
    assert [call.kwargs["run_id"] for call in opener.await_args_list] == [
        "root",
        "child",
    ]
    root.initialize_workspace.assert_awaited_once_with(wiring.workspace_initializer)
    child.initialize_workspace.assert_awaited_once_with(wiring.workspace_initializer)
    root.close.assert_not_called()
    child.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["workspace", "plugin"])
async def test_failure_leaves_binding_cleanup_to_owner_without_retry(phase):
    error = RuntimeError(phase)
    owned = binding("run")
    opener = AsyncMock(side_effect=error)
    if phase == "workspace":
        owned.initialize_workspace.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        await composer(opener).compose(owned, tenant_id="t", agent_id="a")
    assert caught.value is error
    assert opener.await_count == (0 if phase == "workspace" else 1)
    owned.close.assert_not_called()
