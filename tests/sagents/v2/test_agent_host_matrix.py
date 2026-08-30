from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sagents.v2 import AgentHost, AgentRef, SAgentBuilder
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.package.manifest.agents import ApplicationEntrypoint, Instructions
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.registry import AgentPackageRecord, PackageStage
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.model import ModelEventKind, ModelResponse, ModelStreamEvent


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


class _PackageSource:
    def __init__(self, record: AgentPackageRecord) -> None:
        self.record = record
        self.requests: list[tuple[str, str]] = []

    async def get(self, package_id: str, version: str) -> AgentPackageRecord:
        self.requests.append((package_id, version))
        return self.record


def _manifest():
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="com.example.content-team",
        model="test-model",
        base_url="https://model.invalid/v1",
    )
    original_id = package.entrypoint.agent
    assert original_id is not None
    base = package.agents[original_id]
    researcher = base.model_copy(
        update={
            "name": "Researcher",
            "instructions": Instructions(inline="Research facts."),
        }
    )
    writer = base.model_copy(
        update={
            "name": "Writer",
            "instructions": Instructions(inline="Write the answer."),
        }
    )
    return package.model_copy(
        update={
            "agents": {"researcher": researcher, "writer": writer},
            "entrypoint": ApplicationEntrypoint(agent="researcher"),
        }
    )


def _record(*, stage: PackageStage = PackageStage.PUBLISHED) -> AgentPackageRecord:
    manifest = _manifest()
    now = utc_now()
    return AgentPackageRecord(
        package_id=manifest.metadata.id,
        version=manifest.metadata.version,
        revision=3,
        stage=stage,
        manifest=manifest,
        manifest_hash=CompositionResolver().resolve(manifest).manifest_hash,
        created_at=now,
        updated_at=now,
        published_at=now if stage == PackageStage.PUBLISHED else None,
    )


def _runtime_factory(tmp_path: Path, builds: list[str], *, completed: bool = False):
    async def factory(record: AgentPackageRecord, agent_id: str):
        builds.append(agent_id)
        await asyncio.sleep(0)
        steps = (
            (
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED,
                            response=ModelResponse(
                                response_id="response_1",
                                text="done",
                                finish_reason="stop",
                            ),
                        ),
                    )
                ),
            )
            if completed
            else ()
        )
        return (
            SAgentBuilder()
            .with_defaults(session_root=tmp_path / agent_id)
            .with_model_provider(ScriptedModelProvider(steps))
            .build(record.manifest, agent_id=agent_id)
        )

    return factory


def _ref(agent_id: str = "researcher") -> AgentRef:
    return AgentRef(
        package_id="com.example.content-team",
        version="0.1.0",
        agent_id=agent_id,
    )


def _command(agent_id: str = "researcher") -> StartRun:
    return StartRun(
        agent_id=agent_id,
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:caller-value-is-replaced",
        idempotency_key=f"start-{agent_id}",
    )


@pytest.mark.asyncio
async def test_host_routes_multiple_agents_and_builds_each_runtime_once(tmp_path):
    source = _PackageSource(_record())
    builds: list[str] = []
    host = AgentHost(
        source,
        runtime_factory=_runtime_factory(tmp_path, builds),
    )

    first, second = await asyncio.gather(
        host.get_agent(_ref()),
        host.get_agent(_ref()),
    )
    writer = await host.get_agent(_ref("writer"))

    assert first is second
    assert writer is not first
    assert builds == ["researcher", "writer"]
    assert await host.cached_agents() == (_ref(), _ref("writer"))


@pytest.mark.asyncio
async def test_host_binds_package_identity_and_delegates_run_stream(tmp_path):
    record = _record()
    host = AgentHost(
        _PackageSource(record),
        runtime_factory=_runtime_factory(tmp_path, [], completed=True),
    )

    stream = await host.run_stream(_ref(), _command(), CONTEXT)
    events = [event async for event in stream.events]
    result = await stream.wait()
    runtime = await host.get_agent(_ref())
    persisted = await runtime.runtime.get_run(result.run_id)
    persisted_command = await runtime.runtime.session_store.get_start_command(
        result.run_id
    )

    assert result.state == RunState.COMPLETED
    assert events[-1].type == "run.completed"
    assert persisted.resolved_spec_hash == record.manifest_hash
    assert persisted_command.config.metadata["agent_package"] == {
        "package_id": record.package_id,
        "version": record.version,
        "agent_id": "researcher",
        "manifest_hash": record.manifest_hash,
    }


@pytest.mark.asyncio
async def test_host_rejects_unpublished_unknown_and_mismatched_agents(tmp_path):
    unpublished = AgentHost(
        _PackageSource(_record(stage=PackageStage.DRAFT)),
        runtime_factory=_runtime_factory(tmp_path, []),
    )
    with pytest.raises(SageV2Error) as stage:
        await unpublished.get_agent(_ref())
    assert stage.value.info.code == "agent_host.package_not_published"

    published = AgentHost(
        _PackageSource(_record()),
        runtime_factory=_runtime_factory(tmp_path, []),
    )
    with pytest.raises(SageV2Error) as missing:
        await published.get_agent(_ref("missing"))
    assert missing.value.info.code == "agent_host.agent_not_found"

    with pytest.raises(SageV2Error) as mismatch:
        await published.start_run(_ref(), _command("writer"), CONTEXT)
    assert mismatch.value.info.code == "agent_host.command_agent_mismatch"


@pytest.mark.asyncio
async def test_host_rejects_tampered_package_records(tmp_path):
    record = _record().model_copy(update={"manifest_hash": "sha256:tampered"})
    host = AgentHost(
        _PackageSource(record),
        runtime_factory=_runtime_factory(tmp_path, []),
    )

    with pytest.raises(SageV2Error) as invalid:
        await host.get_agent(_ref())

    assert invalid.value.info.code == "agent_host.manifest_hash_mismatch"


@pytest.mark.asyncio
async def test_host_cache_can_be_invalidated_without_deleting_session_data(tmp_path):
    builds: list[str] = []
    host = AgentHost(
        _PackageSource(_record()),
        runtime_factory=_runtime_factory(tmp_path, builds),
    )
    first = await host.get_agent(_ref())

    assert await host.invalidate(_ref()) == 1
    second = await host.get_agent(_ref())

    assert second is not first
    assert builds == ["researcher", "researcher"]

    with pytest.raises(SageV2Error) as closed:
        await first.start_run(_command(), CONTEXT)
    assert closed.value.info.code == "agent.closed"


@pytest.mark.asyncio
async def test_default_host_factory_builds_and_closes_owned_runtime(
    tmp_path, monkeypatch
):
    record = _record()
    route = record.manifest.models["primary"].model_copy(
        update={"credential": "model-key"}
    )
    manifest = record.manifest.model_copy(
        update={
            "credentials": {
                "model-key": CredentialDeclaration(
                    source="env", key="TEST_AGENT_HOST_MODEL_KEY"
                )
            },
            "models": {"primary": route},
        }
    )
    record = record.model_copy(
        update={
            "manifest": manifest,
            "manifest_hash": CompositionResolver().resolve(manifest).manifest_hash,
        }
    )
    monkeypatch.setenv("TEST_AGENT_HOST_MODEL_KEY", "test-key")
    host = AgentHost(_PackageSource(record), session_root=tmp_path)

    runtime = await host.get_agent(_ref())
    assert runtime.runtime.session_store.capabilities["global_session_index"] is False

    await host.close()
    with pytest.raises(SageV2Error) as closed:
        await host.get_agent(_ref())
    assert closed.value.info.code == "agent_host.closed"


@pytest.mark.asyncio
async def test_close_waits_for_an_inflight_build_and_does_not_cache_it(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    async def factory(record: AgentPackageRecord, agent_id: str):
        started.set()
        await release.wait()
        return (
            SAgentBuilder()
            .with_defaults(session_root=tmp_path / agent_id)
            .with_model_provider(ScriptedModelProvider(()))
            .build(record.manifest, agent_id=agent_id)
        )

    host = AgentHost(_PackageSource(_record()), runtime_factory=factory)
    resolving = asyncio.create_task(host.get_agent(_ref()))
    await started.wait()
    closing = asyncio.create_task(host.close())
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(SageV2Error) as closed:
        await resolving
    await closing

    assert closed.value.info.code == "agent_host.closed"
    assert await host.cached_agents() == ()


def test_host_requires_a_default_session_root_or_custom_factory():
    with pytest.raises(ValueError, match="session_root or runtime_factory"):
        AgentHost(_PackageSource(_record()))
