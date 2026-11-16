import asyncio

from ag_ui.core import RunAgentInput, UserMessage

from app.v2.server.config.concurrency import RunConcurrency
from app.v2.server.database import Database, DatabaseSettings
from sagents.v2.composition.revision_store import AgentRevisionStore
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.server.conftest import CompletingJudgeModel, FixtureServerHost, make_settings, scripted_hello
from tests.app.v2.server.test_a2a_resume import _step


class InterruptedModel:
    def __init__(self):
        self.store = None
        self.tool_saved = asyncio.Event()
        self.broken_in_flight = asyncio.Event()
        self.read_file = ScriptedModelProvider((
            _step(1, "", "file_read", {"file_path": "source.txt"}),
        ))

    async def capabilities(self, binding):
        return await self.read_file.capabilities(binding)

    async def stream(self, request):
        command = await self.store.get_start_command(request.run_id)
        if command.session_id == "broken-thread":
            self.broken_in_flight.set()
        elif any(message.tool_call_id == "call-1" for message in request.messages):
            self.tool_saved.set()
        else:
            async for event in self.read_file.stream(request):
                yield event
            return
        await asyncio.Future()


async def test_host_restart_recovers_original_run_and_isolates_unavailable_revision(tmp_path):
    def make_host(model):
        return FixtureServerHost(
            make_settings(tmp_path, log_level="warning"),
            model_provider=CompletingJudgeModel(model),
            database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")),
        )

    tenant = "external-tenant"
    interrupted = InterruptedModel()
    first = make_host(interrupted)
    await first.start()
    try:
        interrupted.store = first.application.service("session.store")
        user = await first.identity.register("restart-owner", "secret1")
        healthy_agent = await first.catalog.create_agent(user.user_id, {
            "id": "healthy", "name": "Healthy", "instructions": "Original recovery instructions",
            "tools": ["file_read"],
        })
        broken_agent = await first.catalog.create_agent(user.user_id, {
            "id": "broken", "name": "Broken", "instructions": "Unavailable revision",
        })
        source = first.paths.workspace_dir(tenant, healthy_agent.id) / "source.txt"
        source.write_text("durable tool output")
        service = first.conversations
        context = first.contexts.for_user(user.user_id)

        async def start(agent, thread_id, run_id, message):
            stream = await service.start(
                RunAgentInput(
                    thread_id=thread_id, run_id=run_id, state={}, tools=[], context=[],
                    messages=[UserMessage(id="input", role="user", content=message)],
                    forwarded_props={},
                ),
                user_id=tenant, agent_id=agent.id,
            )
            await stream.aclose()
            found = await service._find_client_run(thread_id, run_id, context, external=True)
            assert found is not None
            return found[0].run_id

        broken_id = await start(broken_agent, "broken-thread", "broken-run", "block this run")
        healthy_id = await start(healthy_agent, "healthy-thread", "healthy-run", "read the file")
        async with asyncio.timeout(5):
            await interrupted.tool_saved.wait()
            await interrupted.broken_in_flight.wait()
        healthy = await service.session_access.get_run(healthy_id, context)
        broken = await service.session_access.get_run(broken_id, context)
        assert healthy.state == broken.state == RunState.RUNNING
        assert healthy.checkpoint_id and broken.checkpoint_id
        first_events = await service.session_access.read_events(healthy_id, context)
        assert any(event.type == "tool.call.succeeded" for event in first_events)
        await first.catalog.update_agent(user.user_id, healthy_agent.id, {
            "name": "Healthy", "instructions": "New catalog instructions",
        })
        # Restore this archived revision under a persisted change in live capacity.
        await first.update_run_concurrency(RunConcurrency(
            max_concurrent_runs=3, max_concurrent_runs_per_user=1,
        ))
    finally:
        await first.close()

    # The restarted model can only see the original tool output via the checkpoint.
    source.unlink()
    AgentRevisionStore(first.paths.sessions_root)._path(broken.resolved_spec_hash).unlink()
    resumed_model = scripted_hello()
    restarted = make_host(resumed_model)
    await restarted.start()
    try:
        assert restarted.run_concurrency == RunConcurrency(
            max_concurrent_runs=3, max_concurrent_runs_per_user=1,
        )
        assert restarted.application.service("execution.dispatcher").max_concurrent_runs == 3
        assert restarted.execution.model_budget.limit == 3
        (issue,) = restarted.application.recovery_issues
        assert (issue.run_id, issue.resolved_spec_hash) == (broken_id, broken.resolved_spec_hash)
        assert issue.message == "the admitted Agent revision is unavailable"
        service = restarted.conversations
        blocked = await service.result(
            user_id=tenant, agent_id=broken_agent.id, session_id="broken-thread", run_id="broken-run",
        )
        assert blocked["runId"] == "broken-run"
        assert blocked["state"] == "recovery_blocked"
        assert blocked["error"]["code"] == "recovery.agent_revision_unavailable"
        assert blocked["error"]["metadata"]["resolved_spec_hash"] == broken.resolved_spec_hash

        access = service.session_access
        async with asyncio.timeout(5):
            while (resumed := await access.get_run(healthy_id, context)).state not in TERMINAL_RUN_STATES:
                await asyncio.sleep(0.01)
        assert resumed.state == RunState.COMPLETED
        assert resumed.resolved_spec_hash == healthy.resolved_spec_hash
        (request,) = resumed_model.requests
        assert request.run_id == healthy_id
        assert any("Original recovery instructions" in m.model_dump_json() for m in request.messages)
        assert any(m.role == "tool" and "durable tool output" in m.model_dump_json()
                   for m in request.messages)
        events = await access.read_events(healthy_id, context)
        assert [event for event in events if event.type == "tool.call.started"] == [
            event for event in first_events if event.type == "tool.call.started"
        ]
        assert await access.get_run(broken_id, context) == broken
        completed = await service.result(
            user_id=tenant, agent_id=healthy_agent.id, session_id="healthy-thread", run_id="healthy-run",
        )
        assert (completed["runId"], completed["state"], completed["text"]) == (
            "healthy-run", "completed", "hello",
        )
    finally:
        await restarted.close()
