"""A child's transient model retry must not cost it its execution lease."""

from __future__ import annotations

import pytest

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.contracts import ModelResponse, ModelStreamEvent, ModelToolCall
from tests.sagents.v2.test_builder_nested_teams import CONTEXT, Models, delegate, open_app, package, run


def transient_once():
    raised = []

    def step(request):
        if not raised:
            raised.append(request.run_id)
            raise SageV2Error(RuntimeErrorInfo(
                code="model.transport_error", category=ErrorCategory.PROVIDER_TRANSIENT,
                message="connection reset", retryable=True, safe_to_resume=True,
            ))
        return "file_write", {"file_path": "result.txt", "content": "after retry"}

    return step, raised


class ParallelModels(Models):
    """One scripted stage may propose several sibling tool calls."""

    def factory(self, context, dependencies):
        inner = super().factory(context, dependencies)
        owner, stream = self, inner.stream

        async def parallel(request):
            stage = sum(1 for m in request.messages if m.role == "assistant" and m.tool_calls)
            role = next(iter(owner.roles(context)))
            plan = owner.plans.get(role, ())
            if stage < len(plan) and isinstance(plan[stage], list):
                owner.seen.append((role, request))
                calls = tuple(ModelToolCall(tool_call_id=f"{request.run_id}-{stage}-{index}",
                                            name=name, arguments=arguments)
                              for index, (name, arguments) in enumerate(plan[stage]))
                yield ModelStreamEvent(kind="completed", response=ModelResponse(
                    response_id=f"{request.run_id}-{stage}", text="", tool_calls=calls,
                    finish_reason="tool_calls"))
                return
            async for event in stream(request):
                yield event

        inner.stream = parallel
        return inner

    @staticmethod
    def roles(context):
        agent_id = context.agent_configuration["execution_agent_id"]
        yield (context.agent_configuration["package_id"].rsplit(".", 1)[-1]
               if agent_id == "assistant" else agent_id)


@pytest.mark.asyncio
async def test_parallel_delegation_wait_is_not_an_unknown_outcome(tmp_path):
    # Siblings persist a deferred delegation receipt before the step settles.
    step, raised = transient_once()
    models = ParallelModels({
        "root": ([delegate("maker"), ("file_read", {"file_path": "seed.txt"})],),
        "maker": (step,),
    })
    app, bindings, _ = await open_app(tmp_path, models)
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace/seed.txt").write_text("seed")
    try:
        maker = await app.load_agent(package("maker"))
        root = await app.load_agent(package("root", ("maker",)), subagents={"maker": maker})
        result, events = await run(app, root)
        assert raised, "the member never hit its transient model error"
        child_events = await app.runtime.session_store.read_events(raised[0])
        assert result.state.value == "completed", [
            (e.type, e.data) for e in child_events if e.type.endswith("failed")]
        assert any(e.type == "run.completed" for e in child_events)
        assert (tmp_path / "workspace/result.txt").read_text() == "after retry"
        root_events = await app.runtime.session_store.read_events(result.run_id)
        assert not [e for e in root_events if e.type == "tool.call.unknown"]
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_delegated_member_survives_its_transient_model_retry(tmp_path):
    step, raised = transient_once()
    models = Models({"root": (delegate("maker"),), "maker": (step,)})
    app, bindings, _ = await open_app(tmp_path, models)
    try:
        maker = await app.load_agent(package("maker"))
        root = await app.load_agent(package("root", ("maker",)), subagents={"maker": maker})
        result, events = await run(app, root)
        assert raised, "the member never hit its transient model error"
        assert result.state.value == "completed", [
            (e.type, e.data) for e in events if e.type.endswith(("failed", "unknown"))
        ]
        assert (tmp_path / "workspace/result.txt").read_text() == "after retry"
        child_events = await app.runtime.session_store.read_events(raised[0])
        assert not [e for e in child_events if e.type == "tool.call.failed"], [
            e.data for e in child_events if e.type == "tool.call.failed"
        ]
        # Waiting on a deferred child is not an unknown side effect.
        root_events = await app.runtime.session_store.read_events(result.run_id)
        assert not [e for e in root_events if e.type == "tool.call.unknown"]
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_concurrent_drive_joins_deferred_recovery(tmp_path):
    # The woken root recovers while the member runs inline. Another
    # ensure_execution must join that driver, not start a second Turn whose
    # exit would close the shared driver and the member's sandbox lease.
    step, raised = transient_once()
    models = Models({"root": (delegate("maker"),), "maker": (step,)})
    app, bindings, _ = await open_app(tmp_path, models)
    joined = []
    try:
        maker = await app.load_agent(package("maker"))
        root = await app.load_agent(package("root", ("maker",)), subagents={"maker": maker})
        implementation = app._loaded_agents.implementation(root)

        def observe(role, request):
            if role == "maker" and raised and not joined:
                root_run = next(value.run_id for name, value in models.seen if name == "root")
                joined.append(implementation.ensure_execution(root_run, CONTEXT, resume=False))

        models.observe = observe
        result, events = await run(app, root)
        assert joined, "the member never resumed after its retry"
        assert result.state.value == "completed", [
            (e.type, e.data) for e in events if e.type.endswith("failed")
        ]
        assert (await joined[0]).state.value == "completed"
        assert (tmp_path / "workspace/result.txt").read_text() == "after retry"
        root_events = await app.runtime.session_store.read_events(result.run_id)
        assert len([e for e in root_events if e.type == "turn.started"]) == 1
    finally:
        await app.close()
        await bindings.close()
