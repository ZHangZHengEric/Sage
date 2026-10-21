"""Ancestor deadlines and token usage remain shared across child Runs."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.contracts.commands import CommandDecision
    from sagents.v2.contracts.errors import ErrorCategory
    from sagents.v2.runtime.session.contracts import SessionStore

from sagents.v2.model.provider import ModelProvider
from sagents.v2.contracts.errors import RuntimeErrorInfo

from datetime import timedelta

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.events import UsageEventData
from sagents.v2.contracts.items import TextBlock, UsageSummary
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution.budgets import evaluate_run_budget, run_tree_tokens
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from tests.sagents.v2.test_flow_runtime_matrix import CONTEXT


async def start(runtime, key, *, parent=None, session=None, **config):
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent",
            session_id=session,
            parent_run_id=parent,
            input=(InputItem(role="user", content=(TextBlock(text=key),)),),
            config=RunConfig(**config),
            resolved_spec_hash="sha256:budget",
            idempotency_key=key,
        ),
        CONTEXT,
    )
    return await runtime.get_run(handle.run_id)


async def usage(runtime, run, tokens):
    if run.state == RunState.QUEUED:
        run = await runtime.start_execution(
            run_id=run.run_id,
            expected_revision=run.revision,
            context=CONTEXT,
            idempotency_key=f"execute:{run.run_id}",
        )
    result = await runtime.session_store.commit_run(
        run_id=run.run_id,
        expected_revision=run.revision,
        expected_states={RunState.RUNNING},
        new_state=RunState.RUNNING,
        context=CONTEXT,
        idempotency_key=f"usage:{run.run_id}:{tokens}",
        drafts=(
            EventDraft(
                type="usage.recorded",
                data=UsageEventData(usage=UsageSummary(input_tokens=tokens)),
            ),
        ),
    )
    return result.run


@pytest.mark.asyncio
async def test_siblings_share_parent_budget_and_survive_store_replacement(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    root = await start(runtime, "root", max_total_tokens=100)
    root = await usage(runtime, root, 20)
    first = await start(runtime, "first", parent=root.run_id)
    await usage(runtime, first, 40)
    second = await start(runtime, "second", parent=root.run_id, max_total_tokens=50)
    second = await usage(runtime, second, 30)
    other = await start(runtime, "unrelated")
    await usage(runtime, other, 999)
    assert await run_tree_tokens(cast('SessionStore', store), root) == 90
    assert (
        await evaluate_run_budget(cast('SessionStore', store), second, second.created_at)
    ).remaining_tokens == 10
    second = await usage(runtime, second, 10)
    await store.close()
    restored = FilesystemSessionStore(tmp_path)
    try:
        scope = await evaluate_run_budget(
            cast('SessionStore', restored), await restored.get_run(second.run_id), second.created_at
        )
        assert cast(RuntimeErrorInfo, scope.error).code == "budget.max_tokens"
        assert cast(RuntimeErrorInfo, scope.error).metadata["budget_run_id"] == root.run_id
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_child_stops_before_inference_when_ancestor_budget_is_exhausted(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    root = await start(runtime, "root", max_total_tokens=10)
    await usage(runtime, root, 10)
    child = await start(runtime, "child", parent=root.run_id, max_total_tokens=100)
    model = ScriptedModelProvider(())
    loop = AgentLoopEngine(
        runtime=runtime,
        model=cast(ModelProvider, model),
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
    )
    try:
        assert (await loop.execute(child.run_id, CONTEXT)).state == RunState.FAILED
        assert not model.requests
        events = await store.read_events(child.run_id)
        assert not any(event.type == "interaction.requested" for event in events)
        assert cast(RuntimeErrorInfo, (
            await runtime.get_run_result(child.run_id)
        ).error).code == "budget.max_tokens"
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline_seconds", [None, 7 * 24 * 60 * 60])
async def test_task_tree_does_not_inherit_mcp_two_hour_timeout(tmp_path, deadline_seconds):
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    root = await start(runtime, "multi-day-root", deadline_seconds=deadline_seconds)
    child = await start(runtime, "multi-day-child", parent=root.run_id)
    grandchild = await start(runtime, "multi-day-grandchild", parent=child.run_id)
    later = root.created_at + timedelta(days=3)
    try:
        for row in (root, child, grandchild):
            budget = await evaluate_run_budget(cast('SessionStore', store), row, later)
            assert budget.error is None
            assert budget.deadline == (
                None if deadline_seconds is None
                else root.created_at + timedelta(seconds=deadline_seconds)
            )
    finally:
        await store.close()
    restored = FilesystemSessionStore(tmp_path)
    try:
        budget = await evaluate_run_budget(
            cast('SessionStore', restored), await restored.get_run(grandchild.run_id), later,
        )
        assert budget.error is None
        assert (await restored.get_start_command(child.run_id)).config.deadline_seconds is None
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_nested_child_uses_ancestor_absolute_deadline(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    root = await start(runtime, "root", deadline_seconds=30)
    child = await start(runtime, "child", parent=root.run_id, deadline_seconds=300)
    grandchild = await start(runtime, "grandchild", parent=child.run_id)
    try:
        scope = await evaluate_run_budget(
            cast('SessionStore', store), grandchild, root.created_at + timedelta(seconds=31)
        )
        assert cast(RuntimeErrorInfo, scope.error).code == "budget.deadline"
        assert cast(RuntimeErrorInfo, scope.error).metadata["budget_run_id"] == root.run_id
        assert scope.deadline == root.created_at + timedelta(seconds=30)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_parent_budget_failure_settles_waiting_descendants(tmp_path, monkeypatch):
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    root = await start(runtime, "root", max_total_tokens=10)
    child = await start(runtime, "child", parent=root.run_id)
    await usage(runtime, child, 10)
    queued = await start(runtime, "queued", parent=child.run_id)
    from sagents.v2.contracts.commands import CommandReceipt
    from sagents.v2.contracts.errors import RuntimeErrorInfo

    original_cancel = runtime.cancel_run
    attempts = []

    async def cancel(command, context):
        attempts.append(command.run_id)
        if len(attempts) == 1:
            return CommandReceipt(
                command_id="conflict",
                decision=cast('CommandDecision', "rejected"),
                error=RuntimeErrorInfo(
                    code="run.revision_conflict",
                    category=cast('ErrorCategory', "conflict"),
                    message="revision changed",
                ),
            )
        return await original_cancel(command, context)

    monkeypatch.setattr(runtime, "cancel_run", cancel)
    model = ScriptedModelProvider(())
    loop = AgentLoopEngine(
        runtime=runtime,
        model=cast(ModelProvider, model),
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
    )
    try:
        assert (await loop.execute(root.run_id, CONTEXT)).state == RunState.FAILED
        assert (await runtime.get_run(child.run_id)).state == RunState.CANCELLED
        assert (await runtime.get_run(queued.run_id)).state == RunState.CANCELLED
        assert len(attempts) == 3
        assert not model.requests
    finally:
        await store.close()


def test_child_config_inherits_parent_controls_and_narrows_its_own_ceiling():
    from sagents.v2.contracts.commands import RunConfig
    from sagents.v2.package.manifest.resolver import CompositionResolver
    from tests.sagents.v2.test_public_child_model_bindings import MODELS, package

    manifest = package("team")
    worker = manifest.agents["worker"]
    manifest.agents["worker"] = worker.model_copy(
        update={
            "budgets": worker.budgets.model_copy(
                update={"total_tokens": 50, "wall_time_seconds": 20}
            )
        }
    )
    resolver = CompositionResolver(models=MODELS)
    resolved = resolver.resolve(manifest)
    child = resolver.resolve_child_run_config(
        resolved,
        "worker",
        parent_config=RunConfig(
            max_total_tokens=100,
            deadline_seconds=60,
            automatic_stage_continuation=False,
            max_stages=2,
            transient_retry_limit=3,
            priority=4,
        ),
    )
    assert child.max_total_tokens == 50
    assert child.deadline_seconds == 20
    assert not child.automatic_stage_continuation
    assert (child.max_stages, child.transient_retry_limit, child.priority) == (2, 3, 4)
