"""Product controls use a registered App, its original Agent, and public ports."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    pass

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

import asyncio
import ast
from pathlib import Path

import pytest

from sagents.v2.contracts.commands import PauseRun, ResumeRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.contracts.session_commit import ProposeSessionCommit, PublishSessionCommit, RejectSessionCommit
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.sagents.v2.sdk_fixture import build_registered_app
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.test_loaded_agents import package, model, command, context
from tests.sagents.v2.test_memory_matrix import FakeMemoryProvider


@pytest.mark.asyncio
async def test_entrypoint_snapshot_commit_uses_original_revision_and_memory(tmp_path):
    memory = FakeMemoryProvider()
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), providers={"memory.provider": memory})
    try:
        manifest = package()
        definition = manifest.agents[cast('str', manifest.entrypoint.agent)]
        manifest = manifest.model_copy(update={"agents": {
            **manifest.agents, manifest.entrypoint.agent: getattr(definition, 'model_copy')(update={"tools": (*getattr(definition, 'tools'), "search_memory"), "memory": getattr(definition, 'memory').model_copy(update={"auto_write": True})}),
        }})
        agent = await app.load_agent(manifest)
        start = command(agent, "candidate").model_copy(update={"session_concurrency_mode": SessionConcurrencyMode.SNAPSHOT_ISOLATED})
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(start, context(), agent=agent)
        run = await stream.wait()
        assert run.state.value == "completed"
        assert memory.remembered == []
        proposal = await app.entrypoint().propose_session_commit(ProposeSessionCommit(
            run_id=run.run_id, expected_run_revision=run.revision, idempotency_key="propose"), context())
        session = await app.service("session.access").get_session(run.session_id, context())
        changed = manifest.model_copy(update={"metadata": manifest.metadata.model_copy(update={"version": "2"})})
        await app.update_agent(agent=agent, package=changed)
        published = await app.entrypoint().publish_session_commit(PublishSessionCommit(
            proposal_id=proposal.proposal_id, expected_proposal_revision=proposal.revision,
            expected_session_revision=session.revision, idempotency_key="publish"), context())
        assert published.status.value == "published"
        assert [item.content for item in memory.remembered] == ["hello"]
        assert memory.remembered[0].source["run_id"] == run.run_id
        stranger = context().model_copy(update={"actor": context().actor.model_copy(update={"principal_id": "stranger"})})
        with pytest.raises(SageV2Error):
            await app.entrypoint().reject_session_commit(RejectSessionCommit(
                proposal_id=proposal.proposal_id, expected_proposal_revision=published.revision,
                expected_session_revision=session.revision, idempotency_key="deny"), stranger)
        candidate = command(await app.agent_for_run(run.run_id, context()), "reject-candidate").model_copy(
            update={"session_concurrency_mode": SessionConcurrencyMode.SNAPSHOT_ISOLATED})
        candidate_stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(candidate, context(), agent=agent)
        rejected_run = await candidate_stream.wait()
        pending = await app.entrypoint().propose_session_commit(ProposeSessionCommit(
            run_id=rejected_run.run_id, expected_run_revision=rejected_run.revision, idempotency_key="propose-reject"), context())
        candidate_session = await app.service("session.access").get_session(rejected_run.session_id, context())
        rejected = await app.entrypoint().reject_session_commit(RejectSessionCommit(
            proposal_id=pending.proposal_id, expected_proposal_revision=pending.revision,
            expected_session_revision=candidate_session.revision, idempotency_key="reject"), context())
        assert rejected.status.value == "rejected"
        assert len(memory.remembered) == 1
        await candidate_stream.detach()
        await stream.detach()
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_duplicate_continuation_observes_one_execution_and_original_run(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    attempts = []

    class Gated(ScriptedModelProvider):
        async def _stream(self, request):
            attempts.append(request.run_id)
            entered.set()
            await release.wait()
            async for event in super()._stream(request):
                yield event

    provider = Gated(model()._steps)
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=provider)
    try:
        agent = await app.load_agent(package())
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(command(agent, "pause"), context(), agent=agent)
        await asyncio.wait_for(entered.wait(), 5)
        # Detaching an observer must not cancel the SDK-owned execution.
        detached = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(stream.handle.run_id, context(), agent=agent)
        detached.cancel()
        with pytest.raises(asyncio.CancelledError):
            await detached
        # Already running: observing must not schedule another execution.
        observer = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(stream.handle.run_id, context(), agent=agent)
        run = await app.service("session.access").get_run(stream.handle.run_id, context())
        await app.runtime.pause_run(PauseRun(run_id=run.run_id, expected_revision=run.revision, idempotency_key="pause"), context())
        suspended = await asyncio.wait_for(observer, 5)
        assert suspended.state.value == "suspended"
        await stream.wait()
        suspension = await app.service("session.access").get_suspension(suspended.suspension_id, context())
        await app.runtime.resume_run(ResumeRun(run_id=run.run_id, expected_revision=suspended.revision,
            suspension_id=suspension.suspension_id, expected_suspension_revision=suspension.expected_revision,
            idempotency_key="resume"), context())
        resumed_agent = await app.agent_for_run(run.run_id, context())
        first = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(run.run_id, context(), agent=resumed_agent)
        second = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(run.run_id, context(), agent=resumed_agent)
        release.set()
        one, two = await asyncio.wait_for(asyncio.gather(first, second), 10)
        assert one.run_id == two.run_id == run.run_id
        assert one.state.value == two.state.value == "completed"
        assert len(attempts) == 2  # interrupted inference and its resumed generation
        assert len(provider.requests) == 1  # only the resumed inference reaches completion
        terminal = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(run.run_id, context(), agent=resumed_agent)
        assert (await terminal).run_id == run.run_id
        assert len(attempts) == 2
        assert len(provider.requests) == 1
        await stream.detach()
    finally:
        release.set()
        await app.close()


def test_hosts_do_not_import_private_sdk_or_assemble_execution_components():
    root = Path(__file__).resolve().parents[3]
    forbidden = {"HostAgentExecution", "NativeDriver", "AgentLoopEngine", "ModeAwareAgentLoopFactory", "AgentCompositionFactory", "OfficialToolRuntime"}
    violations = []
    for host in (root / "app/v2/desktop/backend", root / "app/v2/server", root / "deploy/images/frontend-test"):
        for path in host.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                modules = [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
                for name in modules:
                    if name and name.startswith("sagents.v2") and any(part.startswith("_") for part in name.split(".")):
                        violations.append(f"{path}:{getattr(node, 'lineno')}: private import {name}")
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sagents.v2"):
                    for alias in node.names:
                        if alias.name.startswith("_") or alias.name in forbidden:
                            violations.append(f"{path}:{node.lineno}: execution/private import {alias.name}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "provision":
                    violations.append(f"{path}:{node.lineno}: host sandbox provisioning")
                if isinstance(node, ast.Attribute) and node.attr in {"child_executor", "continuation_policy"} and isinstance(node.ctx, ast.Store):
                    violations.append(f"{path}:{node.lineno}: execution replacement")
    assert violations == []


@pytest.mark.asyncio
async def test_application_close_settles_continuation_observers(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class Gated(ScriptedModelProvider):
        async def _stream(self, request):
            entered.set()
            await release.wait()
            async for event in super()._stream(request):
                yield event

    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=Gated(model()._steps))
    try:
        agent = await app.load_agent(package())
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(command(agent, "shutdown"), context(), agent=agent)
        await asyncio.wait_for(entered.wait(), 5)
        observer = await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(stream.handle.run_id, context(), agent=agent)
        await asyncio.wait_for(app.close(), 10)
        assert observer.done()
        await asyncio.gather(observer, return_exceptions=True)
        await stream.detach()
    finally:
        release.set()
        await app.close()
