from __future__ import annotations

import base64
import io
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.v2.desktop.backend.catalog import (
    DesktopMcpRecord,
    DesktopModelCompatibilityProfile,
)
from app.v2.desktop.backend.package import desktop_v2_manifest
from app.v2.desktop.backend.service import (
    _usage_percentile,
    AgentCreate,
    AgentRosterContextProvider,
    AgentSettingsPatch,
    ComponentSelectionRequest,
    DesktopV2Settings,
    DesktopV2Service,
    ModelProviderCreate,
    ModelProviderPatch,
    DesktopRunRequest,
)
from app.v2.desktop.backend.schemas import (
    RunMessage,
    RunMessageReferenceContent,
    RunMessageTextContent,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.events import (
    EventDurability,
    EventSource,
    EventSourceType,
    RunEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)
from sagents.v2.agent.multi_agent import AgentMode, AgentRegistry
from sagents.v2.model import (
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.context import ModelConversationSummarizer
from sagents.v2.tool import McpServerConfig, McpToolPlugin
from sagents.v2.runtime.execution.scheduler import LeaseReleaseReason, WorkItem


@asynccontextmanager
async def desktop_execution_lease(service: DesktopV2Service, run_id: str):
    await service.start()
    work_id = new_id("test_work")
    await service.scheduler.submit(
        WorkItem(
            work_id=work_id,
            run_id=run_id,
            available_at=utc_now(),
            idempotency_key=work_id,
        )
    )
    lease = await service.scheduler.claim(
        "test-worker", lease_duration=timedelta(seconds=30), wait_timeout=0
    )
    assert lease is not None
    async with service.driver_session_store.lease_scope(lease):
        yield
    await service.scheduler.release(lease, LeaseReleaseReason.COMPLETED, requeue=False)


def scripted_tool_selection(*tool_names: str) -> ScriptedModelProvider:
    """Keep loop tests deterministic when the Desktop default uses LLM selection."""

    return ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id=new_id("tool_selection_response"),
                            text=json.dumps({"tools": list(tool_names)}),
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )


@pytest.mark.parametrize(
    "language",
    ["system", "zh", "en", "pt", "es", "fr", "de", "ja", "ko", "ru"],
)
def test_desktop_settings_accept_supported_frontend_languages(language: str):
    assert DesktopV2Settings(language=language).language == language


def test_desktop_settings_reject_unknown_frontend_language():
    with pytest.raises(ValueError):
        DesktopV2Settings(language="unsupported")  # type: ignore[arg-type]


def test_usage_percentile_is_interpolated_and_handles_empty_samples():
    assert _usage_percentile([], 0.95) is None
    assert _usage_percentile([240.0], 0.95) == 240.0
    assert _usage_percentile([400.0, 100.0, 300.0, 200.0], 0.50) == 250.0
    assert _usage_percentile([400.0, 100.0, 300.0, 200.0], 0.95) == 385.0


@pytest.mark.asyncio
async def test_builtin_anytool_uses_ephemeral_sidecar_capability(tmp_path: Path):
    service = DesktopV2Service(
        tmp_path,
        sidecar_port=54321,
        sidecar_auth_token="launch-capability",
    )
    record = DesktopMcpRecord(
        user_id="user_1",
        name="AnyTool",
        protocol="streamable_http",
        kind="anytool",
        streamable_http_url="http://stale.invalid/AnyTool",
    )

    config = service._mcp_config(record)

    assert config.url == "http://127.0.0.1:54321/api/mcp/anytool/AnyTool"
    assert config.timeout_seconds == 30
    assert config.call_timeout_seconds == 7200
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == "launch-capability"
    assert record.api_key is None
    await service.close()


@pytest.mark.asyncio
async def test_external_mcp_keeps_its_catalog_api_key(tmp_path: Path):
    service = DesktopV2Service(
        tmp_path,
        sidecar_port=54321,
        sidecar_auth_token="launch-capability",
    )
    record = DesktopMcpRecord(
        user_id="user_1",
        name="remote",
        protocol="streamable_http",
        streamable_http_url="https://mcp.example.test/tools",
        api_key="remote-secret",
    )

    config = service._mcp_config(record)

    assert config.url == "https://mcp.example.test/tools"
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == "remote-secret"
    await service.close()


@pytest.mark.asyncio
async def test_desktop_composition_hash_includes_component_selection_and_config(
    tmp_path,
):
    service = DesktopV2Service(tmp_path)
    defaults = DesktopV2Settings()
    changed = defaults.model_copy(
        update={
            "component_selections": {
                **defaults.component_selections,
                "context.token-estimator": "sage.context.token-estimator.heuristic",
            },
            "component_configs": {"context.token-estimator": {"mode": "precise"}},
        }
    )

    assert service._desktop_spec_hash(
        "sha256:manifest", defaults
    ) != service._desktop_spec_hash("sha256:manifest", changed)
    await service.close()


@pytest.mark.asyncio
async def test_rebuilt_desktop_loop_checks_current_composition_not_stored_hash(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, _, _ = desktop(tmp_path)
    try:
        run, command, _ = await execute(service)
        loaded = await service.application.agent_for_run(run.run_id, service._context("user_1"))
        assert command.resolved_spec_hash == loaded.composition_hash
        changed = command.model_copy(update={"resolved_spec_hash": "sha256:stored-old-composition", "idempotency_key": "bad-hash"})
        with pytest.raises(ValueError, match="identity"):
            await service.application.entrypoint().run_stream(changed, service._context("user_1"), agent=loaded)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_desktop_run_application_exposes_resolved_component_plan(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, _, _ = desktop(tmp_path, runtime={"capabilities": {
        "context.reducer": {"plugin": "sage.context.reducer.window"}}})
    try:
        run, _, _ = await execute(service)
        plan = await service.application.run_configuration(run.run_id, service._context("user_1"))
        bindings = {(value["capability"], value["plugin_id"]) for value in plan["plugins"]}
        assert ("context.reducer", "sage.context.reducer.window") in bindings
        assert ("agent.continuation-policy", "sage.agent.continuation.deterministic") in bindings
        assert not hasattr(service, "_run_application")
        assert not hasattr(service, "_scoped_component")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_workspace_initializer_reuses_agent_scope(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop
    service, _, _ = desktop(tmp_path)
    try:
        settings = await service.get_settings()
        first = await service._ensure_agent_workspace(settings.agent_workspace_path)
        second = await service._ensure_agent_workspace(settings.agent_workspace_path)
        assert first == second
        assert len(service._workspace_initializations) == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_workspace_initializer_runs_before_its_agent_scope_closes(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop
    from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope
    events = []
    class Initializer:
        async def initialize(self, workspace):
            assert not events
            assert workspace.is_dir()
            events.append("initialize")
        async def close(self):
            events.append("close")
    registration = ExtensionRegistration(descriptor=ExtensionDescriptor(
        plugin_id="test.desktop.initializer", name="Initializer", version="1",
        provides=(CapabilityOffer(capability="workspace.initializer", api_version="2"),),
        supported_scopes=frozenset({ExtensionScope.PROCESS})), factory=lambda context, deps: Initializer())
    service, _, _ = desktop(tmp_path, registrations=(registration,), runtime={"capabilities": {
        "workspace.initializer": {"plugin": "test.desktop.initializer"}}})
    try:
        await service._ensure_agent_workspace(str(tmp_path / "workspace"))
        assert events == ["initialize"]
    finally:
        await service.close()
    assert events == ["initialize", "close"]


@pytest.mark.asyncio
async def test_long_lived_component_scope_is_reused_until_service_close(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope
    created, closed = [], []
    class Estimator:
        async def segments(self, command, *, run_id=None):
            return ()
        async def close(self):
            closed.append(self)
    def factory(context, dependencies):
        instance = Estimator()
        created.append(instance)
        return instance
    registration = ExtensionRegistration(descriptor=ExtensionDescriptor(
        plugin_id="test.desktop.estimator", name="Estimator", version="1",
        provides=(CapabilityOffer(capability="context.provider", api_version="2"),),
        supported_scopes=frozenset({ExtensionScope.PROCESS})), factory=factory)
    service, _, _ = desktop(tmp_path, registrations=(registration,), runtime={"capabilities": {
        "context.provider": {"plugin": "test.desktop.estimator", "scope": "process"}}})
    try:
        for _ in range(2):
            run, _, _ = await execute(service)
            assert run.state.value == "completed"
        assert len(created) == 1
        assert not closed
    finally:
        await service.close()
    assert closed == created


@pytest.mark.asyncio
async def test_repeated_loop_composition_does_not_accumulate_agent_scopes(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, tracked_binding
    registration, runtime, bindings = tracked_binding(tmp_path / "workspace")
    service, _, environments = desktop(tmp_path, registrations=(registration,), runtime=runtime)
    try:
        runs = [(await execute(service))[0] for _ in range(3)]
        assert all(run.state.value == "completed" for run in runs)
        assert len({environment.run_id for environment in environments}) == 3
        assert len(bindings) == 3
        assert all(binding.closed for binding in bindings)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_build_loop_closes_provisioned_sandbox_on_composition_failure(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, tracked_binding
    from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope
    acquired = []
    def fail(context, dependencies):
        acquired.append(dependencies.require("execution.environment").run_id)
        raise RuntimeError("composition failed")
    registration = ExtensionRegistration(descriptor=ExtensionDescriptor(
        plugin_id="test.desktop.failure", name="Failing context", version="1",
        provides=(CapabilityOffer(capability="context.provider", api_version="2"),),
        dependencies=(ExtensionDependency(capability="execution.environment"),),
        supported_scopes=frozenset({ExtensionScope.RUN})), factory=fail)
    binding_registration, runtime, bindings = tracked_binding(tmp_path / "workspace")
    runtime["capabilities"]["context.provider"] = {"plugin": "test.desktop.failure", "scope": "run"}
    service, model, _ = desktop(tmp_path, registrations=(binding_registration, registration), runtime=runtime)
    try:
        run, _, _ = await execute(service)
        assert run.state.value == "failed"
        assert acquired == [run.run_id]
        assert not model.requests
        assert len(bindings) == 1
        assert bindings[0].closed
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_desktop_runtime_and_dispatcher_are_owned_by_standard_app(tmp_path):
    service = DesktopV2Service(tmp_path)
    await service.start()
    try:
        assert service.runtime is service.application.runtime
        assert service.dispatcher is service.application.service("execution.dispatcher")
        assert not hasattr(service, "_drivers")
        assert not hasattr(service, "_build_loop")
    finally:
        await service.close()



@pytest.mark.asyncio
async def test_desktop_closes_registered_owned_resource_once(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop
    from tests.sagents.v2.test_run_composition_lifecycle import registration
    closed = []
    class Resource:
        async def close(self):
            closed.append(True)
    service, _, _ = desktop(tmp_path,
        registrations=(registration("test.desktop.resource", lambda scope, deps: Resource()),),
        runtime={"capabilities": {"test.desktop.resource": {"plugin": "test.desktop.resource"}}})
    await service.start()
    await service.close()
    await service.close()
    assert closed == [True]



@pytest.mark.asyncio
async def test_service_close_retries_failed_registered_resource(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop
    from tests.sagents.v2.test_run_composition_lifecycle import registration
    attempts = []
    class Resource:
        async def close(self):
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("transient cleanup")
    service, _, _ = desktop(tmp_path,
        registrations=(registration("test.desktop.resource", lambda scope, deps: Resource()),),
        runtime={"capabilities": {"test.desktop.resource": {"plugin": "test.desktop.resource"}}})
    await service.start()
    with pytest.raises(RuntimeError, match="failed to close"):
        await service.close()
    await service.close()
    await service.close()
    assert len(attempts) == 2
    with pytest.raises(RuntimeError, match="service is closed"):
        await service.start()



@pytest.mark.asyncio
async def test_desktop_run_exposes_frozen_revision_and_binding(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, created = desktop(tmp_path)
    try:
        run, command, _ = await execute(service)
        assert run.state.value == "completed"
        assert created and created[0].run_id == run.run_id
        context = service._context("user_1")
        loaded = await service.application.agent_for_run(run.run_id, context)
        assert command.agent_id == loaded.id
        assert command.resolved_spec_hash == loaded.composition_hash
        configuration = await service.application.run_configuration(run.run_id, context)
        assert configuration["runtime"]["capabilities"]["model.provider"]["plugin"] == "test.desktop.model"
        assert any(item["plugin_id"] == "test.desktop.model" for item in configuration["plugins"])
        assert await service.application.execution_diagnostics(run.run_id, context)
    finally:
        await service.close()



def test_legacy_plan_mode_request_migrates_to_typed_invocation_mode():
    request = DesktopRunRequest(
        agent_id="sage",
        messages=[RunMessage(role="user", text="plan it")],
        plan_mode=True,
    )

    assert request.invocation_mode == "plan"


@pytest.mark.asyncio
async def test_run_recovery_uses_its_frozen_model_route_with_current_credentials(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="openai-responses",
            model="original-model",
            base_url="https://original.example/v1",
            api_keys=["original-key"],
        ),
        "user_1",
    )
    agent = await service._agent("sage", "user_1")
    frozen_agent = agent.model_copy(
        update={
            "config": {
                **agent.config,
                "systemPrefix": "frozen instructions",
                "availableTools": ["file_read"],
            }
        }
    )
    original = await service._provider(frozen_agent, "user_1")
    command = StartRun(
        agent_id="sage",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        config=RunConfig(
            metadata={
                "model_route": service._model_route_snapshot(original),
                "agent_runtime": service._agent_runtime_snapshot(frozen_agent),
            }
        ),
        resolved_spec_hash="sha256:frozen-route",
        idempotency_key="frozen-route",
    )
    handle = await service.runtime.start_run(
        command,
        service._context("user_1"),
    )

    await service.catalog.save_model_provider(
        original.model_copy(
            update={
                "protocol": "anthropic-messages",
                "model": "new-model",
                "base_url": "https://new.example/v1",
                "api_key": "rotated-key",
            }
        )
    )
    await service.catalog.save_agent(
        agent.model_copy(
            update={
                "config": {
                    **agent.config,
                    "systemPrefix": "new instructions",
                    "availableTools": ["file_write"],
                    "approvedShellCommands": ["git status"],
                }
            }
        )
    )
    await service.session_store.close()
    reopened = DesktopV2Service(tmp_path)
    persisted_command = await reopened.session_store.get_start_command(handle.run_id)
    restored_agent = await reopened._agent_for_command(persisted_command, "user_1")
    restored = await reopened._provider_for_command(
        persisted_command, restored_agent, "user_1"
    )

    assert restored_agent.config["systemPrefix"] == "frozen instructions"
    assert restored_agent.config["availableTools"] == ["file_read"]
    assert restored_agent.config["approvedShellCommands"] == ["git status"]
    assert restored.protocol == "openai-responses"
    assert restored.model == "original-model"
    assert restored.base_url == "https://original.example/v1"
    assert restored.api_key == "rotated-key"
    assert "api_key" not in persisted_command.config.metadata["model_route"]
    assert "user_id" not in persisted_command.config.metadata["agent_runtime"]
    await reopened.session_store.close()


@pytest.mark.asyncio
async def test_desktop_fork_uses_the_selected_terminal_run_boundary(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    parent = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="parent"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="desktop-fork-parent",
        ),
        context,
    )
    await service.runtime.cancel_run(
        CancelRun(
            run_id=parent.run_id,
            expected_revision=parent.run_revision,
            idempotency_key="desktop-fork-parent-cancel",
        ),
        context,
    )

    normalized = await service._normalize_desktop_fork_request(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="continue")],
            session_id=parent.session_id,
            fork_source_run_id=parent.run_id,
            session_concurrency_mode=SessionConcurrencyMode.FORK,
        ),
        "user_1",
    )

    assert normalized.base_session_revision == 2
    assert normalized.fork_source_run_id == parent.run_id
    with pytest.raises(ValueError, match="does not match"):
        await service._normalize_desktop_fork_request(
            normalized.model_copy(update={"base_session_revision": 1}),
            "user_1",
        )
    with pytest.raises(SageV2Error) as denied:
        await service._normalize_desktop_fork_request(normalized, "other_user")
    assert denied.value.info.category == ErrorCategory.AUTHORIZATION
    await service.close()


@pytest.mark.asyncio
async def test_desktop_catalog_is_native_seeded_and_persistent(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "sage")
    agents = await service.list_agents("user_1")
    providers = await service.list_model_providers("user_1")

    assert service.diagnostics.root == tmp_path / "sage/runtime/sessions"
    assert agents == [
        {
            "id": "sage",
            "name": "Sage",
            "is_default": True,
            "tool_count": 14,
            "skill_count": 1,
        }
    ]
    assert providers[0]["protocol"] == "openai-responses"
    assert providers[0]["api_key_configured"] is False
    payload = json.loads(
        (tmp_path / "sage/runtime/desktop-catalog.json").read_text(encoding="utf-8")
    )
    assert payload["format_version"] == "sage.desktop-catalog/v2"
    assert "legacy" not in json.dumps(payload).lower()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_authorized_session_index_isolates_corrupt_entry(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "sage")
    service.start = AsyncMock()
    corrupt = SimpleNamespace(session_id="session_corrupt")
    healthy = SimpleNamespace(session_id="session_healthy")
    service.session_index.list = AsyncMock(return_value=(corrupt, healthy))
    service.session_access = SimpleNamespace(
        get_session=AsyncMock(
            side_effect=(
                SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.hash_mismatch",
                        category=ErrorCategory.CORRUPT_STATE,
                        message="snapshot checksum mismatch",
                    )
                ),
                SimpleNamespace(session_id="session_healthy"),
            )
        )
    )
    skipped: set[str] = set()

    visible = await service._authorized_indexed_sessions(
        "user_1",
        skipped_unreadable_sessions=skipped,
    )

    assert visible == (healthy,)
    assert skipped == {"session_corrupt"}
    await service.session_store.close()


@pytest.mark.asyncio
async def test_usage_overview_marks_corrupt_index_entry_as_partial(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "sage")
    await service.list_agents("user_1")

    async def authorized_sessions(
        _user_id: str,
        *,
        skipped_unreadable_sessions: set[str] | None = None,
    ):
        assert skipped_unreadable_sessions is not None
        skipped_unreadable_sessions.add("session_corrupt")
        return ()

    service._authorized_indexed_sessions = AsyncMock(side_effect=authorized_sessions)

    value = await service.usage_overview("user_1", days=7)

    assert value["totals"]["sessions"] == 0
    assert value["data_quality"] == {
        "partial": True,
        "skipped_sessions": 1,
        "skipped_event_sessions": 1,
        "skipped_diagnostic_sessions": 1,
    }
    await service.session_store.close()


@pytest.mark.asyncio
async def test_usage_overview_salvages_diagnostics_when_events_are_corrupt(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "sage")
    await service.list_agents("user_1")
    now = utc_now()
    service._authorized_indexed_sessions = AsyncMock(
        return_value=(
            SimpleNamespace(session_id="session_corrupt"),
            SimpleNamespace(session_id="session_1"),
        )
    )

    def corrupt_state() -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code="session_store.hash_mismatch",
                category=ErrorCategory.CORRUPT_STATE,
                message="snapshot checksum mismatch",
            )
        )

    async def list_session_runs(session_id: str):
        if session_id == "session_corrupt":
            raise corrupt_state()
        return (SimpleNamespace(run_id="run_1"),)

    async def read_session_events(session_id: str):
        if session_id == "session_corrupt":
            raise corrupt_state()
        return (
            SimpleNamespace(
                occurred_at=now,
                type="turn.started",
                run_id="run_1",
                data=SimpleNamespace(),
            ),
            SimpleNamespace(
                occurred_at=now,
                type="tool.call.proposed",
                run_id="run_1",
                data=SimpleNamespace(tool_name="read_file"),
            ),
        )

    async def list_model_requests(*, session_id: str):
        if session_id == "session_corrupt":
            return (
                {
                    "status": "completed",
                    "session_id": session_id,
                    "run_id": "run_corrupt",
                    "started_at": now.isoformat(),
                    "metadata": {"agent_id": "sage"},
                    "request": {"model": "gpt-test", "messages": []},
                    "response": {
                        "usage": {
                            "input_tokens": 5,
                            "output_tokens": 1,
                            "models": ["gpt-test"],
                        }
                    },
                },
            )
        return (
            {
                "status": "completed",
                "session_id": "session_1",
                "run_id": "run_1",
                "started_at": (now - timedelta(seconds=3.9)).isoformat(),
                "first_token_at": (now - timedelta(seconds=2.9)).isoformat(),
                "completed_at": now.isoformat(),
                "metadata": {"agent_id": "sage", "model_binding": "primary"},
                "request": {"model": "gpt-test", "messages": []},
                "response": {
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 30,
                        "cached_input_tokens": 40,
                        "reasoning_tokens": 10,
                        "models": ["gpt-test"],
                        # Legacy Luna-compatible diagnostics stored uncached
                        # and cached prompt tokens as disjoint provider fields.
                        "provider_usage": {
                            "input_tokens": 80,
                            "cached_input_tokens": 40,
                            "output_tokens": 30,
                            "reasoning_tokens": 10,
                        },
                    }
                },
            },
        )

    service.session_store.list_session_runs = AsyncMock(side_effect=list_session_runs)
    service.session_store.get_start_command = AsyncMock(
        return_value=StartRun(agent_id="sage", input=(), resolved_spec_hash="test", idempotency_key="fixture")
    )
    service.session_store.read_session_events = AsyncMock(
        side_effect=read_session_events
    )
    service.diagnostics.list_model_requests = AsyncMock(side_effect=list_model_requests)

    value = await service.usage_overview("user_1", days=7, timezone_offset_minutes=480)

    assert value["totals"] == {
        "input_tokens": 125,
        "output_tokens": 31,
        "cached_input_tokens": 40,
        "reasoning_tokens": 10,
        "total_tokens": 156,
        "model_requests": 2,
        "failed_model_requests": 0,
        "turns": 1,
        "tool_calls": 1,
        "sessions": 2,
        "average_first_token_latency_ms": 1000.0,
        "first_token_latency_p50_ms": 1000.0,
        "first_token_latency_p95_ms": 1000.0,
        "first_token_latency_samples": 1,
        "output_tokens_per_second": 10.0,
        "output_tokens_per_second_p50": 10.0,
        "output_tokens_per_second_p95": 10.0,
        "output_tokens_per_second_samples": 1,
    }
    assert value["models"][0]["name"] == "gpt-test"
    assert value["agents"][0]["name"] == "Sage"
    assert value["agents"][0]["total_tokens"] == 156
    assert value["tools"] == [{"name": "read_file", "count": 1}]
    assert value["daily"][-1]["total_tokens"] == 156
    assert value["data_quality"] == {
        "partial": True,
        "skipped_sessions": 1,
        "skipped_event_sessions": 1,
        "skipped_diagnostic_sessions": 0,
    }
    await service.session_store.close()


@pytest.mark.asyncio
async def test_usage_overview_keeps_events_when_diagnostics_are_unreadable(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "sage")
    await service.list_agents("user_1")
    now = utc_now()
    service._authorized_indexed_sessions = AsyncMock(
        return_value=(SimpleNamespace(session_id="session_1"),)
    )
    service.session_store.list_session_runs = AsyncMock(
        return_value=(SimpleNamespace(run_id="run_1"),)
    )
    service.session_store.get_start_command = AsyncMock(
        return_value=StartRun(agent_id="sage", input=(), resolved_spec_hash="test", idempotency_key="fixture")
    )
    service.session_store.read_session_events = AsyncMock(
        return_value=(
            SimpleNamespace(
                occurred_at=now,
                type="turn.started",
                run_id="run_1",
                data=SimpleNamespace(),
            ),
        )
    )
    service.diagnostics.list_model_requests = AsyncMock(
        side_effect=OSError("diagnostics unavailable")
    )

    value = await service.usage_overview("user_1", days=7)

    assert value["totals"]["turns"] == 1
    assert value["totals"]["sessions"] == 1
    assert value["totals"]["model_requests"] == 0
    assert value["data_quality"] == {
        "partial": True,
        "skipped_sessions": 1,
        "skipped_event_sessions": 0,
        "skipped_diagnostic_sessions": 1,
    }
    await service.session_store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["anthropic-messages", "gemini-generate-content"])
async def test_model_patch_persists_explicit_protocol_and_secret(
    tmp_path: Path, protocol: str
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    value = await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol=protocol,
            model="claude-test",
            base_url="https://api.anthropic.test",
            api_keys=["secret"],
        ),
        "user_1",
    )

    assert value["protocol"] == protocol
    assert value["api_key_configured"] is True
    assert await service.reveal_model_provider_api_key("model_main", "user_1") == {
        "api_key": "secret"
    }
    await service.session_store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["anthropic-messages", "gemini-generate-content"])
async def test_model_provider_can_be_created(tmp_path: Path, protocol: str):
    service = DesktopV2Service(tmp_path)
    created = await service.create_model_provider(
        ModelProviderCreate(
            name="Secondary",
            protocol=protocol,
            model="claude-test",
            base_url="https://anthropic.test",
            api_keys=["secret"],
            supports_tool_calling=False,
            max_tokens=4096,
            max_model_len=100_000,
        ),
        "user_1",
    )

    assert created["name"] == "Secondary"
    assert created["protocol"] == protocol
    assert created["api_key_configured"] is True
    assert created["supports_tool_calling"] is False
    assert created["is_default"] is False

    await service.patch_model_provider(
        created["id"], ModelProviderPatch(is_default=True), "user_1"
    )
    providers = await service.list_model_providers("user_1")
    assert len(providers) == 2
    assert [value["id"] for value in providers if value["is_default"]] == [
        created["id"]
    ]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_manifest_omits_tools_when_probe_marked_them_unsupported(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(supports_tool_calling=False),
        "user_1",
    )
    agent = await service._agent("sage", "user_1")
    provider = await service.catalog.get_model_provider("model_main", "user_1")
    assert provider is not None

    manifest = service._manifest(agent, provider, ("todo_write",), ())

    route = service._model_catalog(agent, provider).models[provider.id]
    assert route.capabilities.tool_calling is False
    assert route.capabilities.parallel_tool_calls is False
    assert manifest.agents[agent.agent_id].tools == ()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_verified_model_compatibility_persists_and_drives_runtime_routes(
    tmp_path: Path,
):
    root = tmp_path / "sage"
    service = DesktopV2Service(root)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="openai-chat-completions",
            model="custom-reasoning-model",
            base_url="https://gateway.test/openai/v1",
            api_keys=["secret"],
        ),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None
    profile = DesktopModelCompatibilityProfile(
        route_fingerprint=service._model_compatibility_fingerprint(candidate),
        max_output_tokens_field="max_tokens",
        effective_max_output_tokens=candidate.max_tokens,
        reasoning_behavior="controllable",
        supported_reasoning_efforts=("low",),
        supports_json_object=True,
        auxiliary_json_compatible=True,
        successful_probes=("connection", "tool_calling"),
    )

    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(compatibility_profile=profile),
        "user_1",
    )
    stored = await service.catalog.get_model_provider("model_main", "user_1")
    assert stored is not None
    assert service._auxiliary_json_compatible(stored) is True
    agent = await service._agent("sage", "user_1")

    assert service._model_catalog(agent, stored).models[stored.id].request.extra == {
        "max_output_tokens_field": "max_tokens"
    }
    assert service._model_catalog(agent, stored).models[stored.id].request.reasoning_effort is None
    judge_provider = await service._model_provider(stored, agent, enable_thinking=False)
    assert judge_provider.config.max_output_tokens_field == "max_tokens"
    assert judge_provider.config.reasoning_parameter_fallback is False
    outgoing = judge_provider.diagnostic_request(
        ModelRequest(
            request_id="judge_request",
            run_id="judge_run",
            model_binding="fast",
            messages=(ModelMessage(role="user", content=(TextBlock(text="judge"),)),),
            max_output_tokens=64,
        )
    )
    assert outgoing["max_tokens"] == 64
    assert "max_completion_tokens" not in outgoing
    assert "extra_body" not in outgoing
    await service.close()

    restored_service = DesktopV2Service(root)
    restored = await restored_service.catalog.get_model_provider("model_main", "user_1")
    assert restored is not None
    assert restored.compatibility_profile == profile
    await restored_service.close()


@pytest.mark.asyncio
async def test_model_route_change_invalidates_old_compatibility_profile(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="openai-chat-completions",
            api_keys=["secret"],
        ),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None
    profile = DesktopModelCompatibilityProfile(
        route_fingerprint=service._model_compatibility_fingerprint(candidate),
        max_output_tokens_field="max_completion_tokens",
        effective_max_output_tokens=candidate.max_tokens,
    )
    assert service._model_compatibility_fingerprint(
        candidate.model_copy(update={"api_key": "rotated-secret"})
    ) != service._model_compatibility_fingerprint(candidate)
    assert service._model_compatibility_fingerprint(
        candidate.model_copy(update={"max_model_len": candidate.max_model_len + 1})
    ) != service._model_compatibility_fingerprint(candidate)
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(compatibility_profile=profile),
        "user_1",
    )

    await service.patch_model_provider(
        "model_main", ModelProviderPatch(model="changed-model"), "user_1"
    )

    changed = await service.catalog.get_model_provider("model_main", "user_1")
    assert changed is not None
    assert changed.compatibility_profile is None
    with pytest.raises(ValueError, match="does not match the saved route"):
        await service.patch_model_provider(
            "model_main",
            ModelProviderPatch(compatibility_profile=profile),
            "user_1",
        )
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_check_uses_draft_and_does_not_persist(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(api_keys=["stored-secret"]),
        "user_1",
    )
    before = await service.catalog.get_model_provider("model_main", "user_1")
    assert before is not None
    probe = AsyncMock(
        return_value={
            "connection": {"supported": True},
            "supports_multimodal": False,
            "supports_structured_output": True,
        }
    )
    service._probe_model_provider_capabilities = probe  # type: ignore[method-assign]

    result = await service.verify_model_provider_capabilities(
        ModelProviderPatch(model="draft-model", base_url="https://draft.test/v1"),
        "user_1",
        provider_id="model_main",
    )

    candidate = probe.await_args.args[0]
    assert candidate.model == "draft-model"
    assert candidate.base_url == "https://draft.test/v1"
    assert candidate.api_key == "stored-secret"
    assert result["supports_multimodal"] is False
    after = await service.catalog.get_model_provider("model_main", "user_1")
    assert after is not None
    assert after.model == before.model
    assert after.base_url == before.base_url
    await service.session_store.close()


@pytest.mark.asyncio
async def test_new_model_capability_check_does_not_create_provider(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    before = await service.list_model_providers("user_1")
    service._probe_model_provider_capabilities = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "connection": {"supported": True},
            "supports_multimodal": True,
            "supports_structured_output": True,
        }
    )

    await service.verify_model_provider_capabilities(
        ModelProviderCreate(
            name="Draft",
            model="draft-model",
            base_url="https://draft.test/v1",
            api_keys=["draft-secret"],
        ),
        "user_1",
    )

    after = await service.list_model_providers("user_1")
    assert [value["id"] for value in after] == [value["id"] for value in before]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_capability_probe_checks_connection_image_and_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(api_keys=["secret"]),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeProvider:
        def __init__(self):
            self.raw_client = SimpleNamespace(aclose=AsyncMock())
            self.requests = []

        async def stream(self, request):
            self.requests.append(request)
            if (
                request.response_schema is not None
                or request.response_format is not None
            ):
                text = '{"ok":true}'
            elif any(
                isinstance(block, ImageBlock)
                for message in request.messages
                for block in message.content
            ):
                text = "red"
            else:
                text = "OK"
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    finish_reason="completed",
                ),
            )

    probe_provider = ProbeProvider()
    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda *args, **kwargs: probe_provider,
    )

    result = await service._probe_model_provider_capabilities(candidate)

    assert result["connection"]["supported"] is True
    assert result["supports_multimodal"] is True
    assert result["supports_structured_output"] is True
    assert result["reasoning_control"]["probed"] is True
    assert result["reasoning_control"]["supported"] is True
    assert result["reasoning_control"]["disable_strategy"] == "omit"
    assert result["reasoning_control"]["supported_efforts"] == [
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert result["valid"] is True
    assert result["successful_probes"] == [
        "connection",
        "multimodal",
        "structured_output",
        "json_object",
        "reasoning_control",
    ]
    assert result["failed_probes"] == ["tool_calling"]
    assert result["skipped_probes"] == []
    assert result["compatibility_profile"]["probe_diagnostics"] == {
        "tool_calling": {
            "status": "unsupported",
            "diagnostic_error": "provider did not return the required probe tool call",
        }
    }
    assert len(probe_provider.requests) == 19
    probe_provider.raw_client.aclose.assert_awaited_once()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_capability_probe_records_supported_reasoning_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="openai-chat-completions",
            model="gpt-5.6-luna",
            base_url="https://azure-luna.test/openai/v1",
            api_keys=["secret"],
        ),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeConfig:
        def __init__(
            self,
            *,
            reasoning_effort=None,
            reasoning_parameter_fallback=True,
        ):
            self.reasoning_effort = reasoning_effort
            self.reasoning_parameter_fallback = reasoning_parameter_fallback

        def model_copy(self, *, update):
            return ProbeConfig(
                reasoning_effort=update.get("reasoning_effort", self.reasoning_effort),
                reasoning_parameter_fallback=update.get(
                    "reasoning_parameter_fallback",
                    self.reasoning_parameter_fallback,
                ),
            )

    class ProbeProvider:
        def __init__(self):
            self.config = ProbeConfig()
            self.raw_client = SimpleNamespace(aclose=AsyncMock())
            self.requests = []

        async def stream(self, request):
            self.requests.append(request)
            if self.config.reasoning_effort == "none":
                error = RuntimeError("reasoning_effort is unsupported")
                error.status_code = 422
                raise error
            text = (
                '{"ok":true}'
                if request.response_schema is not None
                or request.response_format is not None
                else "red"
                if any(
                    isinstance(block, ImageBlock)
                    for message in request.messages
                    for block in message.content
                )
                else "OK"
            )
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    finish_reason="completed",
                ),
            )

    probe_provider = ProbeProvider()
    constructed_routes = []

    def provider_factory(route, *args, **kwargs):
        del args, kwargs
        constructed_routes.append(route)
        return probe_provider

    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        provider_factory,
    )

    result = await service._probe_model_provider_capabilities(candidate)

    assert result["reasoning_control"]["probed"] is True
    assert result["reasoning_control"]["supported"] is True
    assert result["reasoning_control"]["supported_efforts"] == [
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert result["valid"] is True
    assert result["protocol"] == "openai-chat-completions"
    assert constructed_routes
    assert {route.provider for route in constructed_routes} == {
        "openai-chat-completions"
    }
    assert result["successful_probes"] == [
        "connection",
        "multimodal",
        "structured_output",
        "json_object",
        "reasoning_control",
    ]
    assert result["failed_probes"] == ["tool_calling"]
    assert result["skipped_probes"] == []
    assert result["compatibility_profile"]["max_output_tokens_field"] == (
        "max_completion_tokens"
    )
    assert result["compatibility_profile"]["reasoning_disable_strategy"] == "omit"
    assert result["compatibility_profile"]["effective_max_output_tokens"] == 8192
    assert result["compatibility_profile"]["route_fingerprint"] == (
        service._model_compatibility_fingerprint(candidate)
    )
    assert len(probe_provider.requests) == 19
    probe_provider.raw_client.aclose.assert_awaited_once()
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_probe_calibrates_luna_and_runtime_omits_rejected_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="openai-chat-completions",
            model="gpt-5.6-luna",
            base_url="https://azure-luna.test/openai/v1",
            api_keys=["secret"],
            max_tokens=8193,
        ),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeProvider:
        def __init__(self, route):
            self.route = route
            self.raw_client = SimpleNamespace(aclose=AsyncMock())
            self.resolved_max_output_tokens_field = "max_completion_tokens"

        async def stream(self, request):
            if (request.max_output_tokens or 0) > 8192:
                error = RuntimeError("configured output limit is unsupported")
                error.status_code = 422
                raise error
            if self.route.request.reasoning_effort is not None:
                error = RuntimeError("reasoning_effort is unsupported")
                error.status_code = 422
                raise error
            extra = {
                key: value
                for key, value in self.route.request.extra.items()
                if key != "max_output_tokens_field"
            }
            if extra:
                error = RuntimeError("reasoning disable control is unsupported")
                error.status_code = 422
                raise error
            if request.tools:
                response = ModelResponse(
                    response_id=new_id("response"),
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="call_probe",
                            name="sage_capability_probe",
                            arguments={"value": "OK"},
                        ),
                    ),
                    finish_reason="tool_calls",
                )
            elif request.response_schema is not None:
                response = ModelResponse(
                    response_id=new_id("response"),
                    text='{"ok":true}',
                    reasoning="internal",
                    finish_reason="stop",
                )
            elif any(
                isinstance(block, ImageBlock)
                for message in request.messages
                for block in message.content
            ):
                response = ModelResponse(
                    response_id=new_id("response"),
                    text="red",
                    reasoning="internal",
                    finish_reason="stop",
                )
            else:
                response = ModelResponse(
                    response_id=new_id("response"),
                    text="323",
                    reasoning="internal",
                    finish_reason="stop",
                )
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)

    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda route, *args, **kwargs: ProbeProvider(route),
    )

    result = await service._probe_model_provider_capabilities(candidate)

    profile = DesktopModelCompatibilityProfile.model_validate(
        result["compatibility_profile"]
    )
    assert profile.effective_max_output_tokens == 8192
    assert profile.max_output_tokens_field == "max_completion_tokens"
    assert profile.reasoning_behavior == "always"
    assert profile.reasoning_disable_strategy == "omit"
    assert profile.supported_reasoning_efforts == ()
    assert profile.unsupported_reasoning_efforts == (
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )

    verified = candidate.model_copy(update={"compatibility_profile": profile})
    agent = await service._agent("sage", "user_1")
    agent = agent.model_copy(
        update={
            "config": {
                **agent.config,
                "deepThinking": True,
                "thinkingLevel": "low",
            }
        }
    )
    route = service._model_catalog(agent, verified).models[verified.id]
    assert route.request.max_output_tokens == 8192
    assert route.request.reasoning_effort is None
    assert route.request.extra == {"max_output_tokens_field": "max_completion_tokens"}
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_probe_requires_reasoning_to_work_with_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            protocol="openai-chat-completions",
            model="gpt-5.6-luna",
            base_url="https://azure-luna.test/openai/v1",
            api_keys=["secret"],
            max_tokens=8193,
        ),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeProvider:
        resolved_max_output_tokens_field = "max_completion_tokens"

        def __init__(self, route):
            self.route = route
            self.raw_client = SimpleNamespace(aclose=AsyncMock())

        async def stream(self, request):
            effort = self.route.request.reasoning_effort
            if effort is not None and request.tools:
                error = RuntimeError("reasoning with tools is unsupported")
                error.status_code = 422
                raise error
            if request.tools:
                response = ModelResponse(
                    response_id=new_id("response"),
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="call_probe",
                            name="sage_capability_probe",
                            arguments={"value": "OK"},
                        ),
                    ),
                    finish_reason="tool_calls",
                )
            else:
                is_image = any(
                    isinstance(block, ImageBlock)
                    for message in request.messages
                    for block in message.content
                )
                text = (
                    '{"ok":true}'
                    if request.response_schema or request.response_format
                    else "red"
                    if is_image
                    else "323"
                )
                response = ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    reasoning="internal" if effort is not None else "",
                    finish_reason="stop",
                )
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)

    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda route, *args, **kwargs: ProbeProvider(route),
    )

    result = await service._probe_model_provider_capabilities(candidate)
    profile = DesktopModelCompatibilityProfile.model_validate(
        result["compatibility_profile"]
    )

    assert profile.reasoning_behavior == "none"
    assert profile.supported_reasoning_efforts == ()
    assert profile.text_only_reasoning_efforts == (
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    assert result["reasoning_control"]["text_only_efforts"] == list(
        profile.text_only_reasoning_efforts
    )
    assert all(
        not result["reasoning_control"]["effort_outcomes"][effort]["with_tools"][
            "supported"
        ]
        for effort in profile.text_only_reasoning_efforts
    )

    verified = candidate.model_copy(update={"compatibility_profile": profile})
    agent = await service._agent("sage", "user_1")
    agent = agent.model_copy(
        update={
            "config": {
                **agent.config,
                "deepThinking": True,
                "thinkingLevel": "low",
            }
        }
    )
    route = service._model_catalog(agent, verified).models[verified.id]
    assert route.request.reasoning_effort is None
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_probe_persists_nested_reasoning_effort_dialect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeProvider:
        resolved_max_output_tokens_field = "max_tokens"

        def __init__(self, route):
            self.route = route
            self.raw_client = SimpleNamespace(aclose=AsyncMock())

        async def stream(self, request):
            template = self.route.request.extra.get("chat_template_kwargs")
            nested_effort = template.get("reasoning_effort") if template else None
            if nested_effort is not None and nested_effort not in {
                "low",
                "high",
                "max",
            }:
                error = RuntimeError("invalid template reasoning effort")
                error.status_code = 422
                raise error
            if request.tools:
                response = ModelResponse(
                    response_id=new_id("response"),
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="call_probe",
                            name="sage_capability_probe",
                            arguments={"value": "OK"},
                        ),
                    ),
                    finish_reason="tool_calls",
                )
            else:
                is_image = any(
                    isinstance(block, ImageBlock)
                    for message in request.messages
                    for block in message.content
                )
                text = (
                    '{"ok":true}'
                    if request.response_schema or request.response_format
                    else "red"
                    if is_image
                    else "323"
                )
                response = ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    reasoning=(
                        "internal"
                        if self.route.request.reasoning_effort is not None
                        or nested_effort is not None
                        else ""
                    ),
                    finish_reason="stop",
                )
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)

    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda route, *args, **kwargs: ProbeProvider(route),
    )

    result = await service._probe_model_provider_capabilities(candidate)
    profile = DesktopModelCompatibilityProfile.model_validate(
        result["compatibility_profile"]
    )
    assert profile.reasoning_effort_strategy == "chat_template_reasoning_effort"
    assert profile.supported_reasoning_efforts == ("low", "high", "max")

    verified = candidate.model_copy(update={"compatibility_profile": profile})
    agent = await service._agent("sage", "user_1")
    agent = agent.model_copy(
        update={
            "config": {
                **agent.config,
                "deepThinking": True,
                "thinkingLevel": "high",
            }
        }
    )
    route = service._model_catalog(agent, verified).models[verified.id]
    assert route.request.reasoning_effort is None
    assert route.request.extra["chat_template_kwargs"] == {
        "thinking": True,
        "reasoning_effort": "high",
    }
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_probe_persists_effective_reasoning_disable_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeProvider:
        resolved_max_output_tokens_field = None

        def __init__(self, route):
            self.route = route
            self.raw_client = SimpleNamespace(aclose=AsyncMock())

        async def stream(self, request):
            if request.tools:
                response = ModelResponse(
                    response_id=new_id("response"),
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="call_probe",
                            name="sage_capability_probe",
                            arguments={"value": "OK"},
                        ),
                    ),
                    finish_reason="tool_calls",
                )
            else:
                is_image = any(
                    isinstance(block, ImageBlock)
                    for message in request.messages
                    for block in message.content
                )
                text = (
                    '{"ok":true}'
                    if request.response_schema or request.response_format
                    else "red"
                    if is_image
                    else "323"
                )
                disabled = self.route.request.extra.get("enable_thinking") is False
                response = ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    reasoning="" if disabled else "internal",
                    finish_reason="stop",
                )
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)

    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda route, *args, **kwargs: ProbeProvider(route),
    )

    result = await service._probe_model_provider_capabilities(candidate)
    profile = DesktopModelCompatibilityProfile.model_validate(
        result["compatibility_profile"]
    )
    assert profile.reasoning_behavior == "controllable"
    assert profile.reasoning_disable_strategy == "enable_thinking_false"

    verified = candidate.model_copy(update={"compatibility_profile": profile})
    agent = await service._agent("sage", "user_1")
    route = service._model_catalog(agent, verified).models[verified.id]
    assert route.request.reasoning_effort is None
    assert route.request.extra["enable_thinking"] is False
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_probe_returns_partial_results_after_probe_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(api_keys=["secret"]),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeConfig:
        reasoning_effort = None
        reasoning_parameter_fallback = False

        def model_copy(self, *, update):
            value = ProbeConfig()
            value.reasoning_effort = update.get("reasoning_effort")
            value.reasoning_parameter_fallback = update.get(
                "reasoning_parameter_fallback", False
            )
            return value

    class ProbeProvider:
        def __init__(self):
            self.config = ProbeConfig()
            self.raw_client = SimpleNamespace(aclose=AsyncMock())
            self.requests = []

        async def stream(self, request):
            self.requests.append(request)
            is_image = any(
                isinstance(block, ImageBlock)
                for message in request.messages
                for block in message.content
            )
            if self.config.reasoning_effort == "none" or request.response_schema:
                error = RuntimeError("Provider rejected this probe")
                error.status_code = 422
                raise error
            text = (
                '{"ok":true}'
                if request.response_format is not None
                else "red"
                if is_image
                else "OK"
            )
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    finish_reason="completed",
                ),
            )

    probe_provider = ProbeProvider()
    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda *args, **kwargs: probe_provider,
    )

    result = await service._probe_model_provider_capabilities(candidate)

    assert result["valid"] is True
    assert result["successful_probes"] == [
        "connection",
        "multimodal",
        "json_object",
        "reasoning_control",
    ]
    assert result["failed_probes"] == ["structured_output", "tool_calling"]
    assert result["skipped_probes"] == []
    assert result["connection"]["supported"] is True
    assert result["supports_multimodal"] is True
    assert result["supports_structured_output"] is False
    probe_provider.raw_client.aclose.assert_awaited_once()
    await service.close()


@pytest.mark.asyncio
async def test_model_capability_probe_is_invalid_only_when_all_probes_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(api_keys=["secret"]),
        "user_1",
    )
    candidate = await service.catalog.get_model_provider("model_main", "user_1")
    assert candidate is not None

    class ProbeProvider:
        def __init__(self):
            self.raw_client = SimpleNamespace(aclose=AsyncMock())
            self.requests = []

        async def stream(self, request):
            self.requests.append(request)
            error = RuntimeError("Provider rejected this probe")
            error.status_code = 422
            raise error
            yield  # pragma: no cover

    probe_provider = ProbeProvider()
    monkeypatch.setattr(
        "app.v2.desktop.backend.catalog_service.create_registered_model_provider",
        lambda *args, **kwargs: probe_provider,
    )

    with pytest.raises(SageV2Error) as caught:
        await service._probe_model_provider_capabilities(candidate)

    assert caught.value.info.code == "model.capability_probe_all_failed"
    assert caught.value.info.category == ErrorCategory.VALIDATION
    probes = caught.value.info.metadata["probes"]
    assert probes["connection"]["supported"] is False
    assert len(probe_provider.requests) == 7
    probe_provider.raw_client.aclose.assert_awaited_once()
    await service.close()


@pytest.mark.asyncio
async def test_v2_does_not_read_v1_model_or_mcp_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".sage"
    legacy_dir.mkdir()
    legacy = legacy_dir / "sage.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE llm_providers (
          id TEXT PRIMARY KEY, name TEXT, base_url TEXT, api_keys TEXT, model TEXT,
          max_tokens INTEGER, temperature REAL, top_p REAL, presence_penalty REAL,
          max_model_len INTEGER, supports_multimodal INTEGER,
          supports_structured_output INTEGER, is_default INTEGER, user_id TEXT
        );
        CREATE TABLE mcp_servers (name TEXT, user_id TEXT, config TEXT);
        """
    )
    connection.execute(
        "INSERT INTO llm_providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "legacy_model",
            "Legacy",
            "https://legacy.test/v1",
            '["legacy-secret"]',
            "legacy-gpt",
            4096,
            0.2,
            None,
            0.0,
            64_000,
            1,
            1,
            1,
            "default_user",
        ),
    )
    connection.execute(
        "INSERT INTO mcp_servers VALUES (?,?,?)",
        (
            "AnyTool",
            "default_user",
            json.dumps(
                {
                    "kind": "anytool",
                    "protocol": "streamable_http",
                    "streamable_http_url": "http://127.0.0.1:18080/api/mcp/anytool/AnyTool",
                    "disabled": False,
                    "tools": [],
                }
            ),
        ),
    )
    connection.commit()
    connection.close()

    service = DesktopV2Service()
    first = await service.list_model_providers("default_user")
    second = await service.list_model_providers("default_user")
    agent = await service._agent("sage", "default_user")
    mcp = await service.catalog.list_mcp("default_user")

    assert [value["id"] for value in first] == ["model_main"]
    assert second == first
    assert first[0]["name"] == "OpenAI"
    assert first[0]["api_key_configured"] is False
    assert agent.config["llm_provider_id"] == "model_main"
    assert agent.config["fast_llm_provider_id"] == "model_main"
    assert mcp == ()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_model_patch_rejects_an_invalid_route_before_persisting(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    with pytest.raises(ValueError, match="absolute http"):
        await service.patch_model_provider(
            "model_main", ModelProviderPatch(base_url="not-a-url"), "user_1"
        )

    provider = (await service.list_model_providers("user_1"))[0]
    assert provider["base_url"] == "https://api.openai.com/v1"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_catalog_scopes_reused_ids_by_user(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.list_agents("user_2")

    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(protocol="anthropic-messages", model="claude-user-1"),
        "user_1",
    )
    first = (await service.list_model_providers("user_1"))[0]
    second = (await service.list_model_providers("user_2"))[0]

    assert first["model"] == "claude-user-1"
    assert first["protocol"] == "anthropic-messages"
    assert second["model"] != "claude-user-1"
    assert second["protocol"] == "openai-responses"
    payload = json.loads(
        (tmp_path / "runtime/desktop-catalog.json").read_text(encoding="utf-8")
    )
    assert [value["id"] for value in payload["model_providers"]].count(
        "model_main"
    ) == 2
    await service.session_store.close()


@pytest.mark.asyncio
async def test_component_inventory_explains_plugins_and_locks_model_protocol(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    # Exercise the explicitly selected rule-based policy without external model calls.
    settings = await service.get_settings()
    await service.save_settings(settings.model_copy(update={
        "component_selections": {**settings.component_selections,
            "agent.continuation-policy": "sage.agent.continuation.deterministic",
            "memory.recall-query": "sage.memory.recall-query.direct"},
    }))
    inventory = await service.component_inventory("user_1")
    by_id = {value["component"]["component_id"]: value for value in inventory}

    assert set(by_id) == {
        "skill.loading",
        "agent.continuation-policy",
        "context.unit-compactor",
        "context.reducer",
        "context.summarizer",
        "context.summary-store",
        "memory.provider",
        "memory.recall-query",
        "tool.selection-policy",
        "session-memory.provider",
        "observability.diagnostic-sink",
        "observability.log-sink",
        "execution.sandbox",
        "session.store",
        "workspace.initializer",
    }
    assert by_id["agent.continuation-policy"]["active"]["config"] == {
        "repeat_threshold": 3,
        "mode": "deterministic",
        "completion_reason": "text.final",
        "status_source": "turn_status",
        "explicit_statuses": [
            "task_done",
            "need_user_input",
            "blocked",
            "continue_work",
            "failed",
        ],
        "flow_boundaries": ["complete_node", "continue_node"],
        "uses_llm_judge": False,
        "uses_finish_reason": False,
    }
    assert {
        value["plugin_id"] for value in by_id["agent.continuation-policy"]["plugins"]
    } == {
        "sage.agent.continuation.deterministic",
        "sage.agent.continuation.llm-judge",
        "sage.agent.continuation.explicit-status",
    }
    assert by_id["context.reducer"]["active"]["plugin_id"] == (
        "sage.context.reducer.persistent-summary"
    )
    assert by_id["memory.recall-query"]["active"]["plugin_id"] == (
        "sage.memory.recall-query.direct"
    )
    assert {
        value["plugin_id"] for value in by_id["memory.recall-query"]["plugins"]
    } == {
        "sage.memory.recall-query.direct",
        "sage.memory.recall-query.llm",
    }
    assert {
        value["plugin_id"] for value in by_id["tool.selection-policy"]["plugins"]
    } == {
        "sage.tool-selection.direct",
        "sage.tool-selection.llm",
        "sage.tool-selection.lexical",
        "sage.tool-selection.recent",
    }
    assert by_id["tool.selection-policy"]["active"] == {
        "plugin_id": "sage.tool-selection.llm",
        "selected_plugin_id": "sage.tool-selection.llm",
        "source": "default",
        "config": {"max_visible_tools": 24, "model_timeout_seconds": 60.0},
        "pending_restart": False,
    }
    tool_plugins = {
        value["plugin_id"]: value for value in by_id["tool.selection-policy"]["plugins"]
    }
    assert (
        tool_plugins["sage.tool-selection.direct"]["config_schema"]["properties"] == {}
    )
    assert set(
        tool_plugins["sage.tool-selection.llm"]["config_schema"]["properties"]
    ) == {"max_visible_tools", "model_timeout_seconds"}
    assert {
        value["plugin_id"] for value in by_id["context.unit-compactor"]["plugins"]
    } == {
        "sage.context.unit-compactor.reference",
    }
    assert by_id["observability.log-sink"]["active"] == {
        "plugin_id": "sage.logging.filesystem",
        "selected_plugin_id": "sage.logging.filesystem",
        "source": "default",
        "config": {
            "format_version": "sage.log/v1",
            "path": str(tmp_path / "runtime/logs/sage.jsonl"),
            "min_level": "info",
            "max_bytes": 10 * 1024 * 1024,
            "backup_count": 5,
        },
        "pending_restart": False,
    }
    assert {
        value["plugin_id"] for value in by_id["observability.log-sink"]["plugins"]
    } == {
        "sage.logging.filesystem",
        "sage.logging.noop",
        "sage.logging.stdout",
    }
    assert by_id["workspace.initializer"]["active"]["plugin_id"] == (
        "sage.workspace.initializer.claw"
    )
    assert by_id["execution.sandbox"]["active"]["config"] == {
        "workspace_root": "/workspace",
        "workspace_mapping": "active_workspace",
        "filesystem_mode": "workspace",
        "workspace_path_mode": "host",
        "resources": {
            "cpu_percent": 100.0,
            "memory_mb": 1024,
            "disk_mb": 4096,
            "max_processes": 64,
            # Nothing has configured a cgroup subtree or an XFS project mount,
            # so the default settings do not claim kernel hard limits.
            "require_hard_limits": False,
        },
    }
    assert {
        value["plugin_id"] for value in by_id["workspace.initializer"]["plugins"]
    } == {
        "sage.workspace.initializer.bare",
        "sage.workspace.initializer.claw",
    }
    assert by_id["memory.provider"]["active"] == {
        "plugin_id": "sage.memory.filesystem-bm25",
        "selected_plugin_id": "sage.memory.filesystem-bm25",
        "source": "default",
        "config": {
            "path": str(tmp_path / "runtime/memory"),
            "recall": True,
            "auto_write": True,
            "scope_mode": "agent",
        },
        "pending_restart": False,
    }
    assert by_id["session-memory.provider"]["active"] == {
        "plugin_id": "sage.session-memory.sqlite-bm25",
        "selected_plugin_id": "sage.session-memory.sqlite-bm25",
        "source": "default",
        "config": {
            "path": str(tmp_path / "runtime/session-memory"),
            "derived_from": "session.events",
        },
        "pending_restart": False,
    }
    assert by_id["session.store"]["active"]["config"] == {
        "path": str(tmp_path / "runtime/sessions"),
        "authoritative": True,
    }
    with pytest.raises(ValueError, match="not user configurable"):
        await service.select_component(
            "model.provider",
            ComponentSelectionRequest(plugin_id="unregistered.model"),
            "user_1",
        )
    with pytest.raises(SageV2Error) as unavailable:
        await service.select_component(
            "context.reducer",
            ComponentSelectionRequest(plugin_id="unregistered.reducer"),
            "user_1",
        )
    assert unavailable.value.info.code == "extension.not_found"
    logging_selection = await service.select_component(
        "observability.log-sink",
        ComponentSelectionRequest(plugin_id="sage.logging.noop"),
        "user_1",
    )
    assert logging_selection["pending_restart"] is True
    inventory = await service.component_inventory("user_1")
    logging_component = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "observability.log-sink"
    )
    assert logging_component["active"]["plugin_id"] == "sage.logging.filesystem"
    assert logging_component["active"]["selected_plugin_id"] == ("sage.logging.noop")
    assert logging_component["active"]["pending_restart"] is True
    session_memory_selection = await service.select_component(
        "session-memory.provider",
        ComponentSelectionRequest(plugin_id="sage.session-memory.noop"),
        "user_1",
    )
    assert session_memory_selection["plugin_id"] == "sage.session-memory.noop"
    assert session_memory_selection["pending_restart"] is True
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_runtime_failures_are_projected_to_structured_logs(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    event = RuntimeEvent(
        event_id="event_failed",
        type="run.failed",
        occurred_at=utc_now(),
        durability=EventDurability.DURABLE,
        session_id="session_1",
        run_id="run_1",
        session_sequence=1,
        run_sequence=4,
        actor=service._context("user_1").actor,
        source=EventSource(source_type=EventSourceType.AGENT, source_id="sage"),
        data=RunEventData(
            state="failed",
            error=RuntimeErrorInfo(
                code="agent.loop_failed",
                category=ErrorCategory.INTERNAL,
                message="Agent loop crashed",
            ),
        ),
    )

    service._write_runtime_event(event)

    rows = [
        json.loads(line)
        for line in (tmp_path / "runtime/logs/sage.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    failed = rows[-1]
    assert failed["event"] == "run.failed"
    assert failed["level"] == "error"
    assert failed["session_id"] == "session_1"
    assert failed["run_id"] == "run_1"
    assert failed["error"] == {
        "type": "RuntimeErrorInfo",
        "message": "Agent loop crashed",
        "code": "agent.loop_failed",
        "category": "internal",
    }
    await service.close()


@pytest.mark.asyncio
async def test_preflight_failure_is_localized_without_admitting_a_fake_run(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    request = DesktopRunRequest(
        agent_id="missing_agent",
        messages=[RunMessage(role="user", text="开始")],
        response_language="zh-CN",
        idempotency_key="preflight-localized-failure",
    )

    with pytest.raises(SageV2Error) as failure:
        _ = [value async for value in service.run_events(request, "user_1")]
    error = failure.value.info.model_dump(mode="json")
    assert await service.list_sessions("user_1") == []
    assert error["code"] == "desktop.run_start_failed"
    assert error["message"] == "部分信息无效，无法处理该请求。"
    assert error["message_key"] == "error.validation"
    assert error["metadata"]["response_language"] == "zh"
    assert "diagnostic_message" in error["metadata"]
    await service.close()


@pytest.mark.asyncio
async def test_extension_inventory_is_not_a_dynamic_desktop_tool_catalog(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.catalog.save_mcp(
        DesktopMcpRecord(
            user_id="user_1",
            name="files",
            protocol="stdio",
            command="mcp-files",
        )
    )

    inventory = await service.component_inventory("user_1")
    assert not any(
        plugin["plugin_id"] == "native-mcp"
        for component in inventory
        for plugin in component["plugins"]
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_tool_catalog_does_not_hide_in_process_sage_mcp_tools(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    tools = await service.list_tools("user_1")
    by_name = {value["name"]: value for value in tools}

    expected = {
        "generate_image",
        "search_web_page",
        "search_image_from_web",
        "analyze_video",
        "list_tasks",
        "add_task",
        "delete_task",
        "complete_task",
        "enable_task",
        "get_task_details",
        "update_task",
        "send_file_through_im",
        "send_image_through_im",
        "send_message_through_im",
    }
    assert expected.isdisjoint(by_name)
    assert "file_read" in by_name
    assert by_name["file_read"]["type"] == "basic"
    assert by_name["file_read"]["category"] == "files"
    assert by_name["file_read"]["source"] == "文件"
    assert by_name["grep"]["category"] == "code_search"
    assert by_name["grep"]["source"] == "代码检索"
    assert by_name["execute_shell_command"]["category"] == "shell"
    assert by_name["execute_shell_command"]["source"] == "终端"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_native_tool_catalog_localizes_descriptions_and_schema(tmp_path: Path):
    service = DesktopV2Service(tmp_path)

    zh_catalog = {
        value["name"]: value
        for value in await service.list_tools("user_1", language="zh-CN")
    }
    en_catalog = {
        value["name"]: value
        for value in await service.list_tools("user_1", language="en-US")
    }

    assert zh_catalog["file_read"]["description"].startswith("读取文本文件")
    assert (
        zh_catalog["file_read"]["input_schema"]["properties"]["file_path"][
            "description"
        ]
        == "文件虚拟路径"
    )
    assert en_catalog["file_read"]["description"].startswith("Read text")
    assert (
        en_catalog["file_read"]["input_schema"]["properties"]["file_path"][
            "description"
        ]
        == "Virtual path to the file"
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_user_component_selection_is_persisted_with_apply_semantics(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    selection = await service.select_component(
        "context.reducer",
        ComponentSelectionRequest(plugin_id="sage.context.reducer.window"),
        "user_1",
    )

    assert selection["plugin_id"] == "sage.context.reducer.window"
    assert selection["pending_restart"] is False
    settings = await service.get_settings()
    assert settings.component_selections == {
        "context.reducer": "sage.context.reducer.window",
    }
    inventory = await service.component_inventory("user_1")
    reducer = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "context.reducer"
    )
    assert reducer["active"]["plugin_id"] == "sage.context.reducer.window"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_tool_selection_component_keeps_only_the_builtin_count_limit(
    tmp_path: Path,
):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path, runtime={"capabilities": {"tool.selection-policy": {"plugin": "sage.tool-selection.lexical", "config": {"max_visible_tools": 20}}}})
    config = {
        "direct_tool_count_threshold": 10,
        "max_visible_tools": 20,
        "max_tool_schema_tokens": 4096,
        "candidate_top_k": 12,
        "context_turns": 3,
        "max_tool_index_entries": 64,
        "max_tool_index_tokens": 1000,
        "tool_index_description_chars": 72,
        "expansion_batch_limit": 4,
        "max_expanded_tools_per_run": 16,
    }

    selection = await service.select_component(
        "tool.selection-policy",
        ComponentSelectionRequest(
            plugin_id="sage.tool-selection.lexical", config=config
        ),
        "user_1",
    )

    assert selection["plugin_id"] == "sage.tool-selection.lexical"
    assert selection["pending_restart"] is False
    assert selection["config"] == {
        "max_visible_tools": 20,
        "model_timeout_seconds": 60.0,
    }
    settings = await service.get_settings()
    assert settings.component_selections["tool.selection-policy"] == (
        "sage.tool-selection.lexical"
    )
    assert settings.component_configs["tool.selection-policy"] == selection["config"]
    inventory = await service.component_inventory("user_1")
    component = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "tool.selection-policy"
    )
    assert component["active"]["plugin_id"] == "sage.tool-selection.lexical"
    assert component["active"]["config"] == selection["config"]

    try:
        run, _, _ = await execute(service)
        assert run.state.value == "completed"
        assert len(model.requests[0].tools) <= 20
        accepted = await service.application.run_configuration(run.run_id, service._context("user_1"))
        selection = accepted["runtime"]["capabilities"]["tool.selection-policy"]
        assert selection["plugin"] == "sage.tool-selection.lexical"
        assert selection["config"]["max_visible_tools"] == 20
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_hybrid_is_not_selectable_and_explicit_status_builds_real_policy(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, step
    model = ScriptedModelProvider((step(ModelToolCall(tool_call_id="status", name="turn_status", arguments={"status": "task_done", "note": "done"}), text="The work is complete."),))
    service, _, _ = desktop(tmp_path, model=model, runtime={"capabilities": {
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.explicit-status"}}})
    try:
        with pytest.raises(ValueError, match="not user selectable"):
            await service.select_component("agent.continuation-policy", ComponentSelectionRequest(plugin_id="sage.agent.continuation.hybrid"), "user_1")
        await service.select_component("agent.continuation-policy", ComponentSelectionRequest(plugin_id="sage.agent.continuation.explicit-status"), "user_1")
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Work")], approval_mode="auto_approve"))
        assert run.state.value == "completed", [(event.type, event.data.model_dump(mode="json")) for event in await service.session_store.read_events(run.run_id) if event.type in {"tool.call.failed", "run.suspended", "run.failed"}]
        assert "explicit turn status is required" in str(model.requests[0].messages)
        assert "turn_status" in {tool.name for tool in model.requests[0].tools}
        events = await service.session_store.read_events(run.run_id)
        assert any(event.type == "continuation.decided" and event.data.reason_code == "status.complete" for event in events)
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("auxiliary_json_compatible", [True, False])
@pytest.mark.parametrize("explicit_selection", [True, False])
async def test_llm_judge_selection_uses_v1_contract_and_hides_turn_status(tmp_path, monkeypatch, auxiliary_json_compatible, explicit_selection):
    from tests.app.v2.desktop.sdk_fixture import execute, step
    captured, routes = [], []
    class Model(ScriptedModelProvider):
        def __init__(self, route):
            super().__init__(())
            self.route = route
        async def stream(self, request):
            captured.append((self.route, request))
            purpose = request.metadata.get("purpose")
            text = json.dumps({"tools": []}) if purpose == "tool_selection" else json.dumps({"decision": "completed", "reason": "done"}) if purpose == "continuation_judge" else "done"
            for event in step(text=text).events:
                yield event
    def transport(route, credentials, **kwargs):
        routes.append(route)
        return Model(route)
    monkeypatch.setattr("app.v2.desktop.backend.model_providers.create_registered_model_provider", transport)
    service = DesktopV2Service(tmp_path)
    try:
        fast = await service.create_model_provider(ModelProviderCreate(name="Fast Judge", protocol="openai-chat-completions",
            model="judge-fast", base_url="https://judge.test/v1", api_keys=["judge-key"]), "user_1")
        service._auxiliary_json_compatible = lambda provider: auxiliary_json_compatible
        if explicit_selection:
            await service.select_component("agent.continuation-policy", ComponentSelectionRequest(plugin_id="sage.agent.continuation.llm-judge"), "user_1")
        await service.list_agents("user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(fast_llm_provider_id=fast["id"], deep_thinking=True, thinking_level="high"), "user_1")
        run, _, _ = await execute(service)
        assert run.state.value == "completed"
        primary = [(route, request) for route, request in captured if request.metadata.get("purpose") is None]
        judged = [(route, request) for route, request in captured if request.metadata.get("purpose") == "continuation_judge"]
        assert primary and judged
        assert all(route.model == "judge-fast" for route, _ in judged)
        assert all(route.model != "judge-fast" for route, _ in primary)
        assert all("turn_status" not in {tool.name for tool in request.tools} for _, request in primary)
        assert any("decision" in str(request.messages) and "completed" in str(request.messages) for _, request in judged)
        accepted = await service.application.run_configuration(run.run_id, service._context("user_1"))
        assert accepted["runtime"]["capabilities"]["agent.continuation-policy"]["plugin"] == "sage.agent.continuation.llm-judge"
        component = next(value for value in await service.component_inventory("user_1") if value["component"]["component_id"] == "agent.continuation-policy")
        assert component["active"]["config"]["prompt_contract"] == "v1"
        assert component["active"]["config"]["timeout_seconds"] == 60.0
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_openai_reasoning_judge_omits_reasoning_controls(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main",
        ModelProviderPatch(
            model="gpt-5.6-luna",
            base_url="https://azure-luna.test/openai/v1",
            api_keys=["test-key"],
        ),
        "user_1",
    )
    agent = await service._agent("sage", "user_1")
    provider_record = await service._provider(agent, "user_1")

    judge_provider = await service._model_provider(
        provider_record, agent, enable_thinking=False
    )
    request = ModelRequest(
        request_id="judge_request",
        run_id="judge_run",
        model_binding="fast",
        messages=(ModelMessage(role="user", content=(TextBlock(text="judge"),)),),
        response_format="json_object",
    )
    wire_request = judge_provider.diagnostic_request(request)

    assert judge_provider.config.reasoning_effort is None
    assert judge_provider.config.reasoning_parameter_fallback is True
    assert judge_provider.config.extra_body == {}
    assert "extra_body" not in wire_request
    await service.close()


@pytest.mark.asyncio
async def test_memory_provider_selection_applies_on_restart(tmp_path: Path):
    service = DesktopV2Service(tmp_path)

    selection = await service.select_component(
        "memory.provider",
        ComponentSelectionRequest(plugin_id="sage.memory.noop"),
        "user_1",
    )
    inventory = await service.component_inventory("user_1")
    memory = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "memory.provider"
    )

    assert selection["pending_restart"] is True
    assert memory["active"]["plugin_id"] == "sage.memory.filesystem-bm25"
    assert memory["active"]["selected_plugin_id"] == "sage.memory.noop"
    assert memory["active"]["pending_restart"] is True
    await service.close()

    reopened = DesktopV2Service(tmp_path)
    inventory = await reopened.component_inventory("user_1")
    memory = next(
        value
        for value in inventory
        if value["component"]["component_id"] == "memory.provider"
    )
    assert reopened.memory_plugin_id == "sage.memory.noop"
    assert memory["active"]["plugin_id"] == "sage.memory.noop"
    assert memory["active"]["config"]["recall"] is False
    assert memory["active"]["config"]["auto_write"] is False
    assert memory["active"]["pending_restart"] is False
    await reopened.close()


@pytest.mark.asyncio
async def test_create_agent_uses_independent_runnable_defaults(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    created = await service.create_agent(
        AgentCreate(name="Research"),
        "user_1",
    )

    assert created["id"] != "sage"
    assert created["name"] == "Research"
    assert created["llm_provider_id"] == "model_main"
    assert created["fast_llm_provider_id"] == "model_main"
    assert created["agent_mode"] == "simple"
    assert created["max_loop_count"] == 48
    assert created["available_tools"]
    assert created["available_skills"] == ["sage-openui"]
    assert created["is_default"] is False
    assert {value["id"] for value in await service.list_agents("user_1")} == {
        "sage",
        created["id"],
    }
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_settings_patch_persists_frozen_record_and_assignments(
    tmp_path: Path,
):
    data_root = tmp_path / "data"
    skill_source = tmp_path / "skill-source"
    skill_source.mkdir()
    (skill_source / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\n# Review\n",
        encoding="utf-8",
    )
    service = DesktopV2Service(data_root)
    await service.list_agents("user_1")
    await service.import_skill_folder(str(skill_source), "user_1")

    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            name="  Configured Sage  ",
            description="Configured from Desktop v2",
            llm_provider_id="model_main",
            agent_mode="team",
            max_loop_count=64,
            deep_thinking=True,
            thinking_level="high",
            runtime_variables={
                "language": "zh",
                "preferences": {"concise": True},
            },
            available_tools=["todo_write", "file_read", "file_read"],
            available_skills=["review", "review"],
            approved_shell_commands=[
                " git clean -fd ",
                "git reset --hard HEAD~1",
                "git clean -fd",
            ],
        ),
        "user_1",
    )

    assert updated["name"] == "Configured Sage"
    assert updated["description"] == "Configured from Desktop v2"
    assert updated["agent_mode"] == "team"
    assert updated["max_loop_count"] == 64
    assert updated["deep_thinking"] is True
    assert updated["thinking_level"] == "high"
    assert updated["runtime_variables"] == {
        "language": "zh",
        "preferences": {"concise": True},
    }
    assert updated["system_context"] == updated["runtime_variables"]
    assert updated["available_tools"] == ["file_read", "todo_write"]
    assert updated["available_skills"] == ["review"]
    assert updated["approved_shell_commands"] == [
        "git clean -fd",
        "git reset --hard HEAD~1",
    ]
    assert (
        updated["shell_policy"]["user_approved_commands"]
        == updated["approved_shell_commands"]
    )
    assert "git reset --hard" in updated["shell_policy"]["approval_keywords"]
    persisted = await service._agent("sage", "user_1")
    assert persisted.name == "Configured Sage"
    assert persisted.config["availableTools"] == ["file_read", "todo_write"]
    assert persisted.config["availableSkills"] == ["review"]
    assert persisted.config["systemContext"] == updated["runtime_variables"]
    await service.session_store.close()

    reopened = DesktopV2Service(data_root)
    restored = await reopened.get_agent_settings("sage", "user_1")
    assert restored["name"] == "Configured Sage"
    assert restored["available_tools"] == ["file_read", "todo_write"]
    assert restored["available_skills"] == ["review"]
    assert restored["approved_shell_commands"] == updated["approved_shell_commands"]
    assert restored["runtime_variables"] == updated["runtime_variables"]
    await reopened.session_store.close()


@pytest.mark.asyncio
async def test_team_member_assignments_are_validated_and_persisted(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    research = await service.create_agent(AgentCreate(name="Research"), "user_1")
    review = await service.create_agent(AgentCreate(name="Review"), "user_1")

    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(
            agent_mode="team",
            sub_agent_selection_mode="manual",
            available_sub_agent_ids=[review["id"], review["id"]],
        ),
        "user_1",
    )

    assert updated["sub_agent_selection_mode"] == "manual"
    assert updated["available_sub_agent_ids"] == [review["id"]]
    assert research["id"] not in updated["available_sub_agent_ids"]

    with pytest.raises(ValueError, match="cannot include itself"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_sub_agent_ids=["sage"]),
            "user_1",
        )
    with pytest.raises(ValueError, match="unknown sub-agents"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_sub_agent_ids=["missing"]),
            "user_1",
        )
    await service.close()


@pytest.mark.asyncio
async def test_agent_settings_accepts_legacy_system_context_alias(tmp_path: Path):
    service = DesktopV2Service(tmp_path)

    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(system_context={"legacy": True}),
        "user_1",
    )

    assert updated["runtime_variables"] == {"legacy": True}
    assert updated["system_context"] == updated["runtime_variables"]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_shell_approval_can_be_remembered_in_agent_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    monkeypatch.setattr(
        service.session_store,
        "get_start_command",
        AsyncMock(return_value=StartRun(agent_id="sage", input=(), resolved_spec_hash="test", idempotency_key="fixture")),
    )
    interaction = SimpleNamespace(
        allowed_decisions=(
            "approve_once",
            "approve_and_remember",
            "deny",
            "cancel",
        ),
        payload={
            "tool_name": "execute_shell_command",
            "arguments": {"command": " git reset --hard HEAD~1 "},
        },
    )

    remembered = await service._remember_approved_shell_command(
        run_id="run_1",
        interaction=interaction,
        user_id="user_1",
    )

    settings = await service.get_agent_settings("sage", "user_1")
    assert remembered == "git reset --hard HEAD~1"
    assert settings["approved_shell_commands"] == [remembered]
    assert settings["shell_policy"]["user_approved_commands"] == [remembered]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_rejected_interaction_never_persists_remembered_shell_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    run = SimpleNamespace(
        run_id="run_1",
        session_id="session_1",
        revision=3,
        suspension_id="suspension_1",
    )
    suspension = SimpleNamespace(
        suspension_id="suspension_1",
        expected_revision=2,
        interaction_id="interaction_1",
    )
    interaction = SimpleNamespace(
        interaction_id="interaction_1",
        run_id="run_1",
        expected_revision=1,
        allowed_decisions=("approve_and_remember",),
        payload={
            "tool_name": "execute_shell_command",
            "arguments": {"command": "git status"},
        },
    )
    service.application = object()
    service.session_access = SimpleNamespace(
        get_run=AsyncMock(return_value=run),
        get_suspension=AsyncMock(return_value=suspension),
        get_interaction=AsyncMock(return_value=interaction),
    )
    monkeypatch.setattr(service, "_run_context", AsyncMock(return_value=context))
    monkeypatch.setattr(
        service.runtime,
        "reply_interaction",
        AsyncMock(
            return_value=SimpleNamespace(decision=SimpleNamespace(value="rejected"))
        ),
    )
    remember = AsyncMock()
    monkeypatch.setattr(service, "_remember_approved_shell_command", remember)
    monkeypatch.setattr(service, "_index_session", AsyncMock())

    await service.reply_interaction(
        "run_1",
        "interaction_1",
        "approve_and_remember",
        {},
        "user_1",
    )

    remember.assert_not_awaited()
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_assignment_patch_rejects_unknown_and_blank_names(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    with pytest.raises(ValueError, match="unknown tools: made_up_tool"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_tools=["made_up_tool"]),
            "user_1",
        )
    with pytest.raises(ValueError, match="tool names cannot be empty"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_tools=[""]),
            "user_1",
        )
    with pytest.raises(ValueError, match="unknown skills: made-up-skill"):
        await service.patch_agent_settings(
            "sage",
            AgentSettingsPatch(available_skills=["made-up-skill"]),
            "user_1",
        )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_unavailable_mcp_does_not_block_native_tool_configuration(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    await service.catalog.save_mcp(
        DesktopMcpRecord(
            user_id="user_1",
            name="offline",
            protocol="stdio",
            command="sage-command-that-does-not-exist",
        )
    )

    catalog = await service.list_tools("user_1")
    assert "file_read" in {value["name"] for value in catalog}
    updated = await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(available_tools=["file_read", "todo_write"]),
        "user_1",
    )
    assert updated["available_tools"] == ["file_read", "todo_write"]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_skills_are_discovered_and_imported_by_native_filesystem_provider(
    tmp_path: Path,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\n# Review\n",
        encoding="utf-8",
    )
    service = DesktopV2Service(tmp_path / "data")

    result = await service.import_skill_folder(str(source), "user_1")
    catalog = await service.list_skill_catalog("user_1")

    assert result["imported_names"] == ["review"]
    review = next(value for value in catalog if value["name"] == "review")
    assert review["description"] == "Review code"
    assert review["can_delete"] is True
    builtin = next(value for value in catalog if value["name"] == "skill-creator")
    assert builtin["can_delete"] is False
    assert service._skill_provider()._skill_root("skill-creator") == (
        Path(__file__).resolve().parents[4] / "app" / "skills" / "skill-creator"
    )
    assert "# Review" in await service.get_skill_content("review", "user_1")
    with pytest.raises(ValueError, match="already exists"):
        await service.import_skill_folder(str(source), "user_1")

    await service.patch_agent_settings(
        "sage",
        AgentSettingsPatch(available_skills=["review"]),
        "user_1",
    )
    deleted = await service.delete_skill("review", "user_1")

    assert deleted == {"deleted_name": "review"}
    assert not (service.skill_root / "review").exists()
    assert "review" not in {
        value["name"] for value in await service.list_skill_catalog("user_1")
    }
    assert (await service.get_agent_settings("sage", "user_1"))[
        "available_skills"
    ] == []
    with pytest.raises(ValueError, match="Imported Skill not found"):
        await service.delete_skill("skill-creator", "user_1")
    await service.session_store.close()


@pytest.mark.asyncio
async def test_workspace_paths_remain_contained(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "data")
    root = await service.workspace_root(None, "sage")
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    content, media_type = await service.read_file(None, "sage", "hello.txt")

    assert content == b"hello"
    assert media_type == "text/plain; charset=utf-8"
    with pytest.raises(PermissionError):
        await service.read_file(None, "sage", "../outside.txt")
    await service.session_store.close()


@pytest.mark.asyncio
async def test_standalone_workspace_tree_includes_claw_seed_and_user_content(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path / "data")
    root = await service.workspace_root(None, "sage")
    (root / "projects" / "demo").mkdir()
    (root / "projects" / "demo" / "index.html").write_text(
        "<h1>Demo</h1>", encoding="utf-8"
    )

    tree = await service.workspace_tree(None, "sage")
    by_name = {value["name"]: value for value in tree}

    assert {
        "AGENT.md",
        "IDENTITY.md",
        "SOUL.md",
        "USER.md",
        "MEMORY.md",
        "data",
        "logs",
        "memory",
        "projects",
        "temp",
    } <= set(by_name)
    demo = next(
        value for value in by_name["projects"]["children"] if value["name"] == "demo"
    )
    assert [value["path"] for value in demo["children"]] == ["projects/demo/index.html"]
    await service.session_store.close()


@pytest.mark.asyncio
async def test_agent_workspace_uses_the_selected_initializer_plugin(tmp_path: Path):
    service = DesktopV2Service(tmp_path / "data")
    await service.save_settings(
        DesktopV2Settings(
            component_selections={
                "workspace.initializer": "sage.workspace.initializer.bare"
            }
        )
    )

    root = await service.workspace_root(None, "sage")

    assert list(root.iterdir()) == []
    await service.session_store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("network_mode", ["none", "unrestricted"])
async def test_loop_composition_uses_native_model_skill_tool_and_sandbox_plugins(tmp_path, network_mode):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, environments = desktop(tmp_path)
    try:
        settings = await service.get_settings()
        await service.save_settings(settings.model_copy(update={"component_configs": {
            "execution.sandbox": {"network": {"mode": network_mode}}}}))
        run, command, _ = await execute(service)
        assert run.state.value == "completed"
        configuration = await service.application.execution_configuration(run.run_id, service._context("user_1"))
        assert configuration.policy["network"]["mode"] == network_mode
        assert environments[0].sandbox.ref.provider_id == "sage.sandbox.local-workspace"
        names = {tool.name for tool in model.requests[0].tools}
        assert {"file_read", "execute_shell_command", "todo_write", "load_skill"} <= names
        plan = await service.application.run_configuration(run.run_id, service._context("user_1"))
        assert any(value["plugin_id"] == "sage.context.summarizer.model" for value in plan["plugins"])
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_desktop_search_memory_assignment_controls_automatic_recall(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path)
    try:
        await service.list_agents("user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(available_tools=["file_read"]), "user_1")
        run, command, _ = await execute(service)
        assert run.state.value == "completed"
        plan = await service.application.run_configuration(run.run_id, service._context("user_1"))
        assert plan["agent"]["memory"]["recall"] is False
        assert plan["agent"]["memory"]["auto_write"] is False
        assert "search_memory" not in {tool.name for tool in model.requests[0].tools}
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_desktop_memory_recall_query_plugin_selects_llm_generator(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    from tests.sagents.v2.test_standard_execution_configuration import response
    model = ScriptedModelProvider((response(text='{"query":"focused recall"}'), response(text="done")))
    service, _, _ = desktop(tmp_path, model=model, runtime={"capabilities": {
        "memory.recall-query": {"plugin": "sage.memory.recall-query.llm", "scope": "run"}}})
    try:
        await service.list_agents("user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(available_tools=["search_memory"]), "user_1")
        run, _, _ = await execute(service)
        assert run.state.value == "completed"
        assert any(request.metadata.get("purpose") == "memory_recall_query" for request in model.requests)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_workspace_upload_reuses_identical_content_and_indexes_changes(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    first = await service.upload(None, "sage", "image.png", b"first image")
    first_retry = await service.upload(None, "sage", "image.png", b"first image")
    changed = await service.upload(None, "sage", "image.png", b"changed image")
    changed_retry = await service.upload(
        None,
        "sage",
        "image.png",
        b"changed image",
    )
    changed_again = await service.upload(None, "sage", "image.png", b"third image")

    assert first["name"] == first_retry["name"] == "image.png"
    assert first["path"] == first_retry["path"] == "uploads/image.png"
    assert changed["name"] == changed_retry["name"] == "image_1.png"
    assert changed["path"] == changed_retry["path"] == "uploads/image_1.png"
    assert changed["virtual_path"] == changed_retry["virtual_path"]
    assert changed["virtual_path"].endswith("/uploads/image_1.png")
    assert changed_again["name"] == "image_2.png"
    assert changed_again["path"] == "uploads/image_2.png"
    assert changed_again["virtual_path"].endswith("/uploads/image_2.png")

    workspace = await service.workspace_root(None, "sage")
    assert (workspace / "uploads" / "image.png").read_bytes() == b"first image"
    assert (workspace / "uploads" / "image_1.png").read_bytes() == b"changed image"
    assert (workspace / "uploads" / "image_2.png").read_bytes() == b"third image"
    await service.close()


@pytest.mark.asyncio
async def test_sandbox_workspace_root_is_generic_run_configuration(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, environments = desktop(tmp_path)
    try:
        settings = await service.get_settings()
        await service.save_settings(settings.model_copy(update={"component_configs": {
            "execution.sandbox": {"workspace_root": "/project", "workspace_mapping": "active_workspace", "filesystem_mode": "workspace"}}}))
        run, command, _ = await execute(service)
        assert run.state.value == "completed"
        workspace = await service.workspace_root(None, "sage")
        # The native binding exposes the actual authorized workspace to the model.
        assert environments[0].workspace_root == str(workspace.resolve())
        assert command.config.metadata["working_directory"] == "/project"
        assert "api_key" not in command.config.metadata["model_route"]
        assert "user_id" not in command.config.metadata["agent_runtime"]
        uploaded = await service.upload(None, "sage", "note.txt", b"hello")
        assert uploaded["virtual_path"] == "/project/uploads/note.txt"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_plan_mode_is_a_read_only_run_contract(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path)
    try:
        run, command, _ = await execute(service, request=DesktopRunRequest(agent_id="sage",
            messages=[RunMessage(role="user", text="plan this change")], invocation_mode="plan"))
        assert run.state.value == "suspended"
        names = {tool.name for tool in model.requests[0].tools}
        assert {"file_read", "todo_write", "goal_submit"} <= names
        assert names.isdisjoint({"file_write", "execute_shell_command"})
        assert command.invocation_mode == "plan"
        snapshot = await service.application.execution_configuration(run.run_id, service._context("user_1"))
        assert snapshot.policy["process"]["read_only"]
        assert set(snapshot.policy["filesystem"]["allowed_operations"]) <= {"read", "list"}
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_goal_mode_requires_goal_complete_after_rechecking(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute

    def assert_active_goal(request):
            system = "\n".join(
                block.text
                for message in request.messages
                if message.role in {"system", "developer"}
                for block in message.content
                if isinstance(block, TextBlock)
            )
            assert "<active_goal>" in system
            assert "Ship the verified change" in system

    def assert_completion_guidance(request):
            from sagents.v2.i18n import tr

            result_message = next(
                message for message in request.messages
                if message.role == "tool" and message.tool_call_id == "goal_complete_call"
            )
            result = result_message.content[0].value
            assert result["status"] == "completed"
            assert result["summary"] == "All acceptance checks pass."
            assert result["next_step"] == tr(
                "goal.explanation_required", service._context("user_1").language
            )
            system = "\n".join(
                block.text for message in request.messages
                if message.role in {"system", "developer"}
                for block in message.content if isinstance(block, TextBlock)
            )
            assert "<status>completed</status>" in system
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="goal_submit_response",
                            text="I established the goal.",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="goal_submit_call",
                                    name="goal_submit",
                                    arguments={
                                        "content": "Ship the verified change",
                                    },
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
            ScriptedModelStep(
                assertion=assert_active_goal,
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="premature_goal_response",
                            text="I think the goal is done.",
                            finish_reason="stop",
                        ),
                    ),
                ),
            ),
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="goal_complete_response",
                            text="所有验收标准均已通过代码级验证。调用 goal_complete。",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="goal_complete_call",
                                    name="goal_complete",
                                    arguments={
                                        "summary": "All acceptance checks pass."
                                    },
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
            ScriptedModelStep(
                assertion=assert_completion_guidance,
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="goal_final_summary",
                            text="Delivered the change. All acceptance checks pass.",
                            finish_reason="stop",
                        ),
                    ),
                ),
            ),
        )
    )
    service, _, _ = desktop(tmp_path, model=model)
    try:
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Do it")], invocation_mode="goal", approval_mode="auto_approve"))
        assert run.state.value == "completed"
        events = await service.session_store.read_events(run.run_id)
        decisions = [event.data.reason_code for event in events if event.type == "continuation.decided"]
        assert decisions == ["tool.pending", "goal.incomplete", "goal.explanation_required", "goal.complete"]
        assert decisions[-2:] == ["goal.explanation_required", "goal.complete"]
        assert sum(event.type == "tool.call.succeeded" and event.data.tool_name == "goal_complete" for event in events) == 1
        assert len(model.requests) == 4
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_goal_survives_repeated_questionnaires_and_service_restart(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, step
    from sagents.v2.goal.state import GoalStateService
    goal_text = "Build the website and verify persistence"
    session_id = None
    original_goal_id = None
    def active_goal(request):
        assert "<active_goal>" in str(request.messages)
        assert goal_text in str(request.messages)
    for round_number in range(3):
        steps = []
        if round_number == 0:
            steps.append(step(ModelToolCall(tool_call_id="submit", name="goal_submit", arguments={"content": goal_text})))
        if round_number < 2:
            steps.append(step(ModelToolCall(tool_call_id=f"question_{round_number}", name="questionnaire_async", arguments={
                "questions": [{"id": "style", "type": "text", "title": "Which style?"}]}), assertion=active_goal))
        else:
            steps.extend((step(assertion=active_goal), step(ModelToolCall(tool_call_id="complete", name="goal_complete",
                arguments={"summary": "Persistence verified."}), text="Persistence verified.", assertion=active_goal), step()))
        service, _, _ = desktop(tmp_path, model=ScriptedModelProvider(tuple(steps)))
        try:
            await service.list_agents("user_1")
            await service.patch_agent_settings("sage", AgentSettingsPatch(available_tools=["questionnaire_async"]), "user_1")
            run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", session_id=session_id,
                messages=[RunMessage(role="user", text="Use blue.")], invocation_mode="goal", approval_mode="auto_approve"))
            session_id = run.session_id
            assert run.state.value == "completed"
            state = await GoalStateService(service.session_store).get(run.run_id)
            assert state is not None and state.content == goal_text
            if original_goal_id is None:
                original_goal_id = state.created_tool_call_id
            assert state.created_tool_call_id == original_goal_id
            assert state.completed == (round_number == 2)
            reasons = [event.data.reason_code for event in await service.session_store.read_events(run.run_id)
                if event.type == "continuation.decided"]
            if round_number < 2:
                assert reasons[-1] == "tool.questionnaire_ready"
            else:
                assert reasons == ["goal.incomplete", "goal.explanation_required", "goal.complete"]
        finally:
            await service.close()

@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.parametrize("rebuild_before_approval", [False, True])
async def test_confirmed_plan_becomes_the_goal_system_context(tmp_path, rebuild_before_approval):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, step, completed
    content = "1. Update the implementation.\n2. Run the tests."
    def confirmed(request):
        assert "<active_goal>" in str(request.messages)
        assert "<source>plan</source>" in str(request.messages)
        assert "Update the implementation" in str(request.messages)
    remaining = (step(text="The approved Plan has been saved."),
        step(ModelToolCall(tool_call_id="goal_complete", name="goal_complete", arguments={"summary": "The plan and checks passed."}),
            text="The confirmed plan was executed and verified.", assertion=confirmed), step(text="Checks passed."))
    first = step(ModelToolCall(tool_call_id="submit_plan", name="goal_submit", arguments={"content": content}))
    service, _, _ = desktop(tmp_path, model=ScriptedModelProvider((first, *remaining)))
    try:
        plan, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Plan it")],
            invocation_mode="plan"))
        assert plan.state.value == "suspended"
        suspension = await service.session_store.get_suspension(plan.suspension_id)
        interaction = await service.session_store.get_interaction(suspension.interaction_id)
        assert interaction.payload["tool_name"] == "goal_submit"
        assert interaction.payload["arguments"]["content"] == content
        if rebuild_before_approval:
            await service.close()
            service, _, _ = desktop(tmp_path, model=ScriptedModelProvider(remaining))
            await service.start()
        await service.reply_interaction(plan.run_id, interaction.interaction_id, "approve_once", {}, "user_1")
        assert (await completed(service, plan.run_id)).state.value == "completed"
        goal, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", session_id=plan.session_id,
            messages=[RunMessage(role="user", text="Execute it")], invocation_mode="goal", approval_mode="auto_approve"))
        assert goal.state.value == "completed"
        names = [event.data.tool_name for event in await service.session_store.read_events(goal.run_id) if event.type == "tool.call.succeeded"]
        assert "goal_complete" in names
        assert "goal_submit" not in names
    finally:
        await service.close()

@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_sandbox_workspace_path_can_match_the_real_workspace(tmp_path, explicit):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, _, environments = desktop(tmp_path)
    try:
        if explicit:
            settings = await service.get_settings()
            await service.save_settings(settings.model_copy(update={"component_configs": {"execution.sandbox": {
                "workspace_root": "/workspace", "workspace_path_mode": "host", "workspace_mapping": "active_workspace", "filesystem_mode": "workspace"}}}))
        run, command, _ = await execute(service)
        assert run.state.value == "completed"
        workspace = await service.workspace_root(None, "sage")
        assert environments[0].sandbox.filesystem.normalize_path("note.txt") == str(workspace.resolve() / "note.txt")
        assert command.config.metadata["working_directory"] == str(workspace.resolve())
        uploaded = await service.upload(None, "sage", "note.txt", b"hello")
        assert uploaded["virtual_path"] == str(workspace.resolve() / "uploads/note.txt")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_isolated_sandbox_rejects_host_workspace_path_mode(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()

    with pytest.raises(ValueError, match="requires a fixed virtual workspace path"):
        await service.save_settings(
            settings.model_copy(
                update={
                    "component_selections": {
                        **settings.component_selections,
                        "execution.sandbox": "sage.sandbox.ephemeral",
                    },
                    "component_configs": {
                        "execution.sandbox": {
                            "workspace_path_mode": "host",
                            "workspace_mapping": "isolated",
                        }
                    },
                }
            )
        )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_sandbox_rejects_provider_incompatible_workspace_mapping(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()

    with pytest.raises(ValueError, match="requires active_workspace"):
        await service.save_settings(
            settings.model_copy(
                update={
                    "component_configs": {
                        "execution.sandbox": {"workspace_mapping": "isolated"}
                    }
                }
            )
        )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_ephemeral_sandbox_keeps_an_isolated_configured_workspace(
    tmp_path: Path,
):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, environments = desktop(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(
        settings.model_copy(
            update={
                "component_selections": {
                    **settings.component_selections,
                    "execution.sandbox": "sage.sandbox.ephemeral",
                },
                "component_configs": {
                    "execution.sandbox": {
                        "workspace_root": "/sandbox",
                        "workspace_mapping": "isolated",
                        "filesystem_mode": "workspace",
                    }
                },
            }
        )
    )
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    workspace = await service.workspace_root(None, "sage")
    try:
        run, command, _ = await execute(service)
        assert run.state.value == "completed", (await service.session_store.get_run_result(run.run_id)).error
        sandbox = environments[0].sandbox
        assert sandbox.ref.provider_id == "sage.sandbox.ephemeral"
        assert sandbox.filesystem.normalize_path(".") == "/sandbox"
        with pytest.raises(PermissionError, match="outside"):
            sandbox.filesystem.normalize_path(str(workspace / "AGENT.md"))
        assert command.config.metadata["working_directory"] == "/sandbox"
        assert command.config.metadata["workspace_files"] == "Working directory: /sandbox\n(Empty isolated sandbox)"
        diagnostics = await service.application.execution_diagnostics(run.run_id, service._context("user_1"))
        assert diagnostics["recovery"] == "same_process"
        assert diagnostics["interpreter"] is None
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_desktop_turn_status_drives_the_real_continuation_policy(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="status_response",
                            text="The requested work is complete.",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="status_call",
                                    name="turn_status",
                                    arguments={"status": "task_done", "note": "done"},
                                ),
                            ),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
        )
    )
    service, _, _ = desktop(tmp_path, model=model)
    try:
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Do it")], invocation_mode="normal", approval_mode="auto_approve"))
        assert run.state.value == "completed"
        events = await service.session_store.read_events(run.run_id)
        decision = next(event for event in events if event.type == "continuation.decided")
        assert decision.data.reason_code == "status.complete"
        assert any(event.type == "tool.call.succeeded" for event in events)
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "present", "absent"),
    [
        (
            "simple",
            set(),
            {"sys_spawn_agent", "sys_delegate_task", "sys_team_delegate_task"},
        ),
        ("fibre", {"sys_spawn_agent", "sys_delegate_task"}, {"sys_team_delegate_task"}),
        ("team", {"sys_team_delegate_task"}, {"sys_spawn_agent", "sys_delegate_task"}),
    ],
)
async def test_desktop_agent_modes_expose_only_their_real_delegation_tools(tmp_path, mode, present, absent):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path)
    try:
        await service.list_agents("user_1")
        member = await service.create_agent(AgentCreate(name="Research"), "user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(agent_mode=mode), "user_1")
        run, _, _ = await execute(service)
        assert run.state.value == "completed"
        names = {tool.name for tool in model.requests[0].tools}
        assert present <= names
        assert names.isdisjoint(absent)
        content = "\n".join(block.text for message in model.requests[0].messages for block in message.content if isinstance(block, TextBlock))
        if mode != "simple":
            assert member["id"] in content
            assert "Research" in content
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_new_fibre_session_composes_before_authoritative_session_exists(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path)
    try:
        await service.list_agents("user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(agent_mode="fibre"), "user_1")
        with pytest.raises(SageV2Error):
            await service.session_store.get_session("session_client_generated")
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", session_id="session_client_generated",
            messages=[RunMessage(role="user", text="work")]))
        assert run.state.value == "completed"
        assert run.session_id == "session_client_generated"
        assert {"sys_spawn_agent", "sys_delegate_task"} <= {tool.name for tool in model.requests[0].tools}
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_delegated_fibre_context_declares_a_leaf_execution_boundary():
    roster = AgentRosterContextProvider(
        AgentRegistry(),
        AgentMode.FIBRE,
        allow_delegation=False,
    )

    segments = await roster.segments(
        StartRun(
            agent_id="child",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:leaf-context",
            idempotency_key="leaf-context",
            invocation_mode="delegation",
        )
    )

    assert len(segments) == 1
    assert segments[0].segment_id == "agent_delegation_boundary"
    assert "leaf agent" in segments[0].content
    assert "Do not create, spawn, or delegate" in segments[0].content
    assert "sys_spawn_agent" not in segments[0].content


@pytest.mark.asyncio
async def test_desktop_team_member_executes_as_leaf(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, step
    member_id = None
    class Model(ScriptedModelProvider):
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                value = step(ModelToolCall(tool_call_id="delegate", name="sys_team_delegate_task", arguments={
                    "tasks": [{"agent_id": member_id, "content": "Review"}]}))
            else:
                value = step()
            for event in value.events:
                yield event
    model = Model(())
    service, _, environments = desktop(tmp_path, model=model)
    try:
        await service.list_agents("user_1")
        member = await service.create_agent(AgentCreate(name="Team Lead"), "user_1")
        member_id = member["id"]
        await service.patch_agent_settings(member_id, AgentSettingsPatch(agent_mode="team"), "user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(agent_mode="team", sub_agent_selection_mode="manual", available_sub_agent_ids=[member_id]), "user_1")
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Review")], approval_mode="auto_approve"))
        assert run.state.value == "completed"
        child = next(value for value in environments if value.command.parent_run_id == run.run_id)
        requests = [request for request in model.requests if request.run_id == child.run_id]
        assert requests
        assert all({"sys_spawn_agent", "sys_delegate_task", "sys_team_delegate_task"}.isdisjoint(tool.name for tool in request.tools) for request in requests)
        accepted = await service.application.run_configuration(child.run_id, service._context("user_1"))
        assert accepted["parent_run_id"] == run.run_id
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fibre", "team"])
async def test_multi_agent_modes_register_only_manually_selected_members(tmp_path, mode):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path)
    try:
        await service.list_agents("user_1")
        research = await service.create_agent(AgentCreate(name="Research"), "user_1")
        review = await service.create_agent(AgentCreate(name="Review"), "user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(agent_mode=mode, sub_agent_selection_mode="manual",
            available_sub_agent_ids=[review["id"]]), "user_1")
        run, _, _ = await execute(service)
        assert run.state.value == "completed"
        content = "\n".join(block.text for message in model.requests[0].messages for block in message.content if isinstance(block, TextBlock))
        assert review["id"] in content
        assert "Review" in content
        assert research["id"] not in content
        assert "Research" not in content
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_loop_composition_includes_enabled_configured_mcp_tools(
    tmp_path: Path, monkeypatch,
):
    class Session:
        async def list_tools(self):
            return {
                "tools": [
                    {
                        "name": "lookup",
                        "description": "Lookup",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }

    @asynccontextmanager
    async def session_factory(config):
        yield Session()

    bridge = McpToolPlugin(
        (
            McpServerConfig(
                name="remote", protocol="streamable_http", url="https://mcp.test"
            ),
        ),
        session_factory=session_factory,
    )
    from tests.app.v2.desktop.sdk_fixture import desktop, execute
    service, model, _ = desktop(tmp_path)

    async def bridge_for_user(user_id):
        return bridge

    monkeypatch.setattr("sagents.v2.tool.plugins.mcp._sdk_session", session_factory)
    await service.catalog.save_mcp(DesktopMcpRecord(user_id="user_1", name="remote", protocol="streamable_http", streamable_http_url="https://mcp.test"))
    await service.list_agents("user_1")
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1"
    )
    agent = await service._agent("sage", "user_1")
    config = dict(agent.config)
    config["availableTools"] = [*config["availableTools"], "mcp_remote_lookup"]
    await service.catalog.save_agent(agent.model_copy(update={"config": config}))
    agent = await service._agent("sage", "user_1")
    try:
        run, _, _ = await execute(service)
        assert run.state.value == "completed"
        assert "mcp_remote_lookup" in {tool.name for tool in model.requests[0].tools}
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_language,expected_language", [("zh-CN", "zh"), ("en-US", "en"), ("system", "en"), ("unknown", "en")])
async def test_desktop_command_freezes_language_identity_time_and_workspace_context(
    tmp_path: Path, requested_language, expected_language,
):
    service = DesktopV2Service(tmp_path)
    await service.initialize_agent_workspace()
    (service.agent_workspace / "SOUL.md").write_text("Be precise", encoding="utf-8")
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    agent = agent.model_copy(
        update={
            "config": {
                **agent.config,
                "systemContext": {
                    "response_language": "en-US",
                    "preference": "concise",
                },
            }
        }
    )
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    resolved = service._manifest(agent, provider, ("todo_write",), ())
    resolved = CompositionResolver(models=service._model_catalog(agent, provider)).resolve(resolved)
    workspace = await service.workspace_root(None, "sage")

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="hello")],
            response_language=requested_language,
            session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_session_revision=0,
        ),
        resolved,
        agent=agent,
        workspace=workspace,
    )

    metadata = command.config.metadata
    assert command.session_concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED
    assert command.base_session_revision == 0
    assert metadata["response_language"] == expected_language
    assert metadata["system_context"] == {"preference": "concise"}
    assert metadata["identity_documents"]["SOUL"] == "Be precise"
    assert set(metadata["identity_documents"]) == {
        "AGENT",
        "IDENTITY",
        "SOUL",
        "USER",
        "MEMORY",
    }
    assert metadata["working_directory"] == workspace.resolve().as_posix()
    assert (
        datetime.strptime(metadata["current_time"], "%a, %d %b %Y %H:%M:%S %z").tzinfo
        is not None
    )
    assert metadata["workspace_files"].startswith(f"Working directory: {workspace.resolve().as_posix()}\n")
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_command_inlines_workspace_images_for_multimodal_models(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    settings = await service.get_settings()
    await service.save_settings(
        settings.model_copy(
            update={
                "component_configs": {
                    **settings.component_configs,
                    "execution.sandbox": {
                        "workspace_root": "/workspace",
                        "workspace_path_mode": "host",
                        "workspace_mapping": "active_workspace",
                        "filesystem_mode": "workspace",
                    },
                }
            }
        )
    )
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    workspace = await service.workspace_root(None, "sage")
    image_path = workspace / "uploads" / "image.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = b"\x89PNG\r\n\x1a\n"
    image_path.write_bytes(image_bytes)
    resolved = CompositionResolver(models=service._model_catalog(agent, provider)).resolve(
        service._manifest(agent, provider, ("file_read",), ())
    )

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[
                RunMessage(
                    role="user",
                    text="What is in this image?",
                    content=[
                        RunMessageTextContent(text="What is in "),
                        RunMessageReferenceContent(
                            name="image.png",
                            path=image_path.as_posix(),
                        ),
                        RunMessageTextContent(text="this image?"),
                    ],
                )
            ],
        ),
        resolved,
        agent=agent,
        provider=provider,
        workspace=workspace,
    )

    attachment = command.input[0]
    assert isinstance(attachment.content[0], TextBlock)
    assert attachment.content[0].text == "What is in"
    assert f"![image.png](<{image_path.as_posix()}>)" in attachment.content[1].text
    image = next(block for block in attachment.content if isinstance(block, ImageBlock))
    assert image.uri == "data:image/png;base64,iVBORw0KGgo="
    assert image.mime_type == "image/png"
    assert image.alt == image_path.as_posix()
    assert attachment.content[-1].text == "this image?"
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_command_preserves_interleaved_structured_references(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    workspace = await service.workspace_root(None, "sage")
    resolved = CompositionResolver(models=service._model_catalog(agent, provider)).resolve(
        service._manifest(agent, provider, ("file_read",), ())
    )

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[
                RunMessage(
                    role="user",
                    text="请检查前后内容",
                    content=[
                        RunMessageTextContent(text="请检查"),
                        RunMessageReferenceContent(
                            name="requirements copy.md",
                            path="docs/requirements copy.md",
                        ),
                        RunMessageTextContent(text="前后内容"),
                    ],
                )
            ],
        ),
        resolved,
        agent=agent,
        provider=provider,
        workspace=workspace,
    )

    blocks = command.input[0].content
    assert [block.kind for block in blocks] == ["text", "text", "text"]
    assert blocks[0].text == "请检查"
    assert blocks[1].text == "[requirements copy.md](<docs/requirements copy.md>)"
    assert blocks[2].text == "前后内容"
    assert all("@" not in block.text for block in blocks)
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_command_compresses_large_images_without_mutating_upload(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    workspace = await service.workspace_root(None, "sage")
    image_path = workspace / "uploads" / "large.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    source = Image.effect_noise((2_048, 1_536), 100).convert("RGB")
    source.save(image_path, format="PNG")
    original = image_path.read_bytes()
    resolved = CompositionResolver(models=service._model_catalog(agent, provider)).resolve(
        service._manifest(agent, provider, ("file_read",), ())
    )

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="Inspect this image")],
            attachment_paths=[image_path.as_posix()],
        ),
        resolved,
        agent=agent,
        provider=provider,
        workspace=workspace,
    )

    attachment = command.input[-1]
    image = next(block for block in attachment.content if isinstance(block, ImageBlock))
    encoded = image.uri.partition(",")[2]
    outbound = base64.b64decode(encoded)
    with Image.open(io.BytesIO(outbound)) as compressed:
        assert compressed.format == "JPEG"
        assert max(compressed.size) == 1_536
    assert len(outbound) < len(original)
    assert image.mime_type == "image/jpeg"
    assert image.uri.startswith("data:image/jpeg;base64,")
    assert image_path.read_bytes() == original
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_command_keeps_images_as_references_for_text_only_models(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    provider = (await service.catalog.list_model_providers("user_1"))[0].model_copy(
        update={"supports_multimodal": False}
    )
    workspace = await service.workspace_root(None, "sage")
    image_path = workspace / "uploads" / "image.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    resolved = CompositionResolver(models=service._model_catalog(agent, provider)).resolve(
        service._manifest(agent, provider, ("file_read",), ())
    )

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="Inspect the attachment")],
            attachment_paths=["/workspace/uploads/image.png"],
        ),
        resolved,
        agent=agent,
        provider=provider,
        workspace=workspace,
    )

    assert all(not isinstance(block, ImageBlock) for block in command.input[-1].content)
    assert (
        "![image.png](</workspace/uploads/image.png>)"
        in command.input[-1].content[0].text
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_command_keeps_non_image_files_as_markdown_references(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")
    agent = await service._agent("sage", "user_1")
    provider = (await service.catalog.list_model_providers("user_1"))[0]
    workspace = await service.workspace_root(None, "sage")
    resolved = CompositionResolver(models=service._model_catalog(agent, provider)).resolve(
        service._manifest(agent, provider, ("file_read",), ())
    )

    command = service._command(
        DesktopRunRequest(
            agent_id="sage",
            messages=[RunMessage(role="user", text="Inspect the attachment")],
            attachment_paths=["/workspace/docs/requirements.md"],
        ),
        resolved,
        agent=agent,
        provider=provider,
        workspace=workspace,
    )

    assert (
        "[requirements.md](</workspace/docs/requirements.md>)"
        in command.input[-1].content[0].text
    )
    await service.session_store.close()


@pytest.mark.asyncio
async def test_desktop_exposes_snapshot_propose_publish_and_session_inventory(
    tmp_path: Path,
):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute

    service, _, _ = desktop(tmp_path)
    handle, _, _ = await execute(service, request=DesktopRunRequest(
        agent_id="sage", messages=[RunMessage(role="user", text="candidate")],
        session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
    ))
    assert handle.state.value == "completed"

    proposal = await service.propose_session_commit(handle.run_id, "user_1")
    published = await service.publish_session_commit(
        proposal.proposal_id,
        SessionMergeStrategy.REQUIRE_UNCHANGED_BASE,
        "user_1",
    )
    snapshot = await service.session_snapshot(handle.session_id, "user_1")

    assert published.status == SessionCommitProposalStatus.PUBLISHED
    assert snapshot["commit_proposals"] == [published.model_dump(mode="json")]
    assert (
        await service.session_commit_proposals(handle.session_id, "user_1")
        == snapshot["commit_proposals"]
    )
    await service.close()


@pytest.mark.asyncio
async def test_desktop_session_index_is_not_authoritative(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="index-boundary",
        ),
        service._context("user_1"),
    )
    await service._index_session(handle.session_id)
    assert [value["session_id"] for value in await service.list_sessions("user_1")] == [
        handle.session_id
    ]
    assert (
        tmp_path / "runtime" / "sessions" / handle.session_id / "state.json"
    ).is_file()
    assert (tmp_path / "runtime" / ".session-store" / "store.json").is_file()
    assert not (tmp_path / "runtime" / "session-store").exists()

    service.session_index.path.unlink()
    assert await service.list_sessions("user_1") == []
    assert (await service.session_store.get_session(handle.session_id)).session_id == (
        handle.session_id
    )
    await service.close()


@pytest.mark.asyncio
async def test_desktop_session_queries_enforce_durable_owner(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    owner = service._context("owner")
    other = service._context("other")
    owner_run = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="owner"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="owner-session",
        ),
        owner,
    )
    other_run = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="other"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="other-session",
        ),
        other,
    )
    await service._index_session(owner_run.session_id)
    await service._index_session(other_run.session_id)

    visible = await service.list_sessions("owner")

    assert [value["session_id"] for value in visible] == [owner_run.session_id]
    with pytest.raises(SageV2Error) as denied:
        await service.session_snapshot(other_run.session_id, "owner")
    assert denied.value.info.category == ErrorCategory.AUTHORIZATION
    with pytest.raises(SageV2Error):
        await service.delete_session(other_run.session_id, "owner")
    assert (
        await service.session_store.get_session(other_run.session_id)
    ).session_id == other_run.session_id
    await service.close()


@pytest.mark.asyncio
async def test_desktop_session_tree_exposes_child_run_routing_metadata(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    parent = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="parent"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="tree-parent",
        ),
        context,
    )
    child = await service.runtime.start_run(
        StartRun(
            session_id=parent.session_id,
            agent_id="reviewer",
            input=(InputItem(role="user", content=(TextBlock(text="child"),)),),
            config=RunConfig(
                metadata={
                    "task_name": "检查实现",
                    "original_task": "检查快速排序实现",
                    "parent_tool_call_id": "call_delegate_quicksort",
                }
            ),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            parent_run_id=parent.run_id,
            invocation_mode="delegation",
            resolved_spec_hash="sha256:test",
            idempotency_key="tree-child",
        ),
        context,
    )

    nodes = await service.session_tree(parent.session_id, "user_1")

    assert len(nodes) == 1
    assert nodes[0]["session"]["session_id"] == child.session_id
    assert nodes[0]["session"]["parent_session_id"] == parent.session_id
    assert nodes[0]["run"]["run_id"] == child.run_id
    assert nodes[0]["parent_run_id"] == parent.run_id
    assert nodes[0]["parent_tool_call_id"] == "call_delegate_quicksort"
    assert nodes[0]["agent_id"] == "reviewer"
    assert nodes[0]["task_name"] == "检查实现"
    assert nodes[0]["original_task"] == "检查快速排序实现"
    stream = service.subscribe_session_tree(parent.session_id, "user_1")
    discovered = json.loads(await anext(stream))
    child_event = json.loads(await anext(stream))
    assert discovered["kind"] == "session.discovered"
    assert discovered["session"]["session_id"] == child.session_id
    assert discovered["parent_tool_call_id"] == "call_delegate_quicksort"
    assert child_event["kind"] == "session.event"
    assert child_event["session_id"] == child.session_id
    assert child_event["parent_session_id"] == parent.session_id
    assert child_event["run_id"] == child.run_id
    await stream.aclose()
    await service.close()


@pytest.mark.asyncio
async def test_desktop_parent_delete_removes_descendants_from_index(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    context = service._context("user_1")
    parent = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="parent"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="delete-index-parent",
        ),
        context,
    )
    child = await service.runtime.start_run(
        StartRun(
            session_id=parent.session_id,
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="child"),)),),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            resolved_spec_hash="sha256:test",
            idempotency_key="delete-index-child",
        ),
        context,
    )
    await service._index_session(parent.session_id)
    await service._index_session(child.session_id)

    for handle, key in ((parent, "cancel-parent"), (child, "cancel-child")):
        await service.runtime.cancel_run(
            CancelRun(
                run_id=handle.run_id,
                expected_revision=handle.run_revision,
                idempotency_key=key,
            ),
            context,
        )
    await service.delete_session(parent.session_id, "user_1")

    # DELETE is idempotent at the Desktop boundary. A stale UI record must still
    # be removable after the authoritative Session plugin has already deleted it.
    await service.delete_session(parent.session_id, "user_1")

    assert await service.list_sessions("user_1") == []
    for session_id in (parent.session_id, child.session_id):
        with pytest.raises(SageV2Error) as missing:
            await service.session_store.get_session(session_id)
        assert missing.value.info.code == "session.not_found"
    await service.close()


@pytest.mark.asyncio
async def test_desktop_index_failure_does_not_rollback_session_commit(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    handle = await service.runtime.start_run(
        StartRun(
            agent_id="sage",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="index-failure",
        ),
        service._context("user_1"),
    )

    async def fail(_value):
        raise OSError("index unavailable")

    service.session_index.upsert = fail
    await service._index_session(handle.session_id)
    assert (await service.session_store.get_session(handle.session_id)).revision == 1
    await service.session_store.close()


def test_workspace_prompt_listing_stays_within_two_levels(tmp_path: Path):
    root = tmp_path / "workspace"
    nested = root / "src" / "pkg" / "deep"
    nested.mkdir(parents=True)
    (nested / "hidden.py").write_text("secret", encoding="utf-8")
    (root / "README.md").write_text("hello", encoding="utf-8")
    (root / "src" / "main.py").write_text("print()", encoding="utf-8")

    listing = DesktopV2Service._workspace_prompt_listing(root)

    assert "README.md" in listing
    assert "src/main.py" in listing
    assert "src/pkg" in listing
    assert "hidden.py" not in listing


@pytest.mark.asyncio
async def test_skill_loading_component_schema_and_validation(tmp_path):
    service = DesktopV2Service(tmp_path)
    try:
        inventory = await service.component_inventory("user_1")
        component = next(v for v in inventory if v["component"]["component_id"] == "skill.loading")
        schema = component["plugins"][0]["config_schema"]
        assert "max_active_tokens" not in schema["properties"]
        assert schema["properties"]["max_active_characters"]["default"] == 24000
        for invalid in (0, -1, True, 1.5, "12000"):
            with pytest.raises(ValueError):
                await service.select_component("skill.loading", ComponentSelectionRequest(
                    plugin_id="sage.skill.loading.lazy", config={"max_active_characters": invalid},
                ), "user_1")
        await service.select_component("skill.loading", ComponentSelectionRequest(
            plugin_id="sage.skill.loading.lazy", config={"max_active_characters": 48000},
        ), "user_1")
        inventory = await service.component_inventory("user_1")
        component = next(v for v in inventory if v["component"]["component_id"] == "skill.loading")
        assert component["selected_config"] == {"max_active_characters": 48000}
        settings = await service.get_settings()
        manifest = desktop_v2_manifest(session_root=tmp_path,
            component_selections=settings.component_selections,
            component_configs=settings.component_configs)
        assert manifest.runtime.selections("skill.loading")[0].config == {"max_active_characters": 48000}
    finally:
        await service.session_store.close()


@pytest.mark.asyncio
async def test_summary_plugin_defaults_match_runtime_and_hide_host_binding(tmp_path):
    import inspect
    service = DesktopV2Service(tmp_path)
    try:
        inventory = await service.component_inventory("user_1")
        component = next(v for v in inventory if v["component"]["component_id"] == "context.summarizer")
        plugin = next(p for p in component["plugins"] if p["plugin_id"] == "sage.context.summarizer.model")
        properties = plugin["config_schema"]["properties"]
        defaults = inspect.signature(ModelConversationSummarizer).parameters
        for key in ("model_binding", "max_source_tokens", "timeout_seconds"):
            assert properties[key]["default"] == defaults[key].default
        assert properties["model_binding"]["readOnly"] is True
        with pytest.raises(ValueError):
            await service.select_component("context.summarizer", ComponentSelectionRequest(
                plugin_id="sage.context.summarizer.model", config={"model_binding": "other"},
            ), "user_1")
        await service.select_component("context.summarizer", ComponentSelectionRequest(
            plugin_id="sage.context.summarizer.model",
            config={"max_source_tokens": 16000, "timeout_seconds": 30},
        ), "user_1")
    finally:
        await service.session_store.close()


@pytest.mark.asyncio
async def test_all_user_plugin_fields_have_defaults_or_are_host_owned(tmp_path):
    from jsonschema import Draft202012Validator
    service = DesktopV2Service(tmp_path)
    try:
        inventory = await service.component_inventory("user_1")
        checked = 0
        for component in inventory:
            if component["component"]["selection_mode"] != "user":
                continue
            for plugin in component["plugins"]:
                schema = plugin["config_schema"]
                for name, field in schema.get("properties", {}).items():
                    kind = field.get("type")
                    if not isinstance(kind, str) or kind not in {"string", "integer", "number", "boolean"}:
                        continue
                    if field.get("readOnly") and "default" not in field:
                        continue
                    assert "default" in field, (plugin["plugin_id"], name)
                    Draft202012Validator(field).validate(field["default"])
                    checked += 1
                if plugin["plugin_id"] in {"sage.tool-selection.lexical", "sage.tool-selection.recent"}:
                    assert "model_timeout_seconds" not in schema["properties"]
        assert checked > 0
    finally:
        await service.session_store.close()


@pytest.fixture
async def sandbox_composition_host(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop
    service, _, _ = desktop(tmp_path)
    await service.start()
    try:
        yield service
    finally:
        await service.close()


async def test_local_sandbox_command_path_config_is_forwarded_and_separates_cache(sandbox_composition_host):
    from tests.app.v2.desktop.sdk_fixture import execute
    host = sandbox_composition_host
    runs = []
    for value in ("/first/bin", "/second/bin"):
        settings = await host.get_settings()
        await host.save_settings(settings.model_copy(update={"component_configs": {
            **settings.component_configs, "execution.sandbox": {"command_path": value}}}))
        run, _, _ = await execute(host)
        assert run.state.value == "completed"
        runs.append(run.run_id)
    first = await host.application.execution_configuration(runs[0], host._context("user_1"))
    second = await host.application.execution_configuration(runs[1], host._context("user_1"))
    assert first.tool_environment["command_path"] == "/first/bin"
    assert second.tool_environment["command_path"] == "/second/bin"
    assert first.configuration_id != second.configuration_id


async def test_local_sandbox_read_paths_config_is_forwarded_and_separates_cache(sandbox_composition_host, tmp_path):
    from tests.app.v2.desktop.sdk_fixture import execute
    host = sandbox_composition_host
    runs, paths = [], []
    for name in ("first-runtime", "second-runtime"):
        directory = tmp_path / name
        directory.mkdir()
        paths.append(str(directory.resolve()))
        settings = await host.get_settings()
        await host.save_settings(settings.model_copy(update={"component_configs": {
            **settings.component_configs, "execution.sandbox": {"read_paths": [paths[-1]]}}}))
        run, _, _ = await execute(host)
        assert run.state.value == "completed"
        runs.append(run.run_id)
    first = await host.application.execution_diagnostics(runs[0], host._context("user_1"))
    second = await host.application.execution_diagnostics(runs[1], host._context("user_1"))
    assert paths[0] in first["runtime_read_paths"]
    assert paths[1] not in first["runtime_read_paths"]
    assert paths[1] in second["runtime_read_paths"]
    assert paths[0] not in second["runtime_read_paths"]
    assert first["configuration_id"] != second["configuration_id"]


@pytest.mark.asyncio
async def test_preflight_preserves_typed_resource_failure_details(tmp_path, monkeypatch):
    service = DesktopV2Service(tmp_path)
    await service.list_agents("user_1")

    async def quota_failure(*args, **kwargs):
        raise SageV2Error(RuntimeErrorInfo(
            code="sandbox.workspace_quota_exceeded",
            category=ErrorCategory.RESOURCE_LOST,
            message="existing workspace exceeds resources.disk_mb",
            message_key="error.sandbox.workspace_quota_exceeded",
            message_params={"used_mb": 5000, "limit_mb": 4096},
            metadata={"used_bytes": 5000 * 1024**2, "side_effect_state": "not_applied"},
        ))

    monkeypatch.setattr(service, "_agent", quota_failure)
    request = DesktopRunRequest(
        agent_id="sage", messages=[RunMessage(role="user", text="继续")],
        response_language="zh-CN", idempotency_key="typed-quota-failure",
    )
    with pytest.raises(SageV2Error) as failure:
        _ = [value async for value in service.run_events(request, "user_1")]
    error = failure.value.info.model_dump(mode="json")
    assert await service.list_sessions("user_1") == []
    assert error["code"] == "sandbox.workspace_quota_exceeded"
    assert error["category"] == "resource_lost"
    assert "5000" in error["message"] and "4096" in error["message"]
    assert error["metadata"]["used_bytes"] == 5000 * 1024**2
    assert "部分信息无效" not in error["message"]
    await service.close()


@pytest.mark.asyncio
async def test_configured_disk_quota_reaches_main_and_child_sandboxes(tmp_path):
    from tests.app.v2.desktop.sdk_fixture import desktop, execute, step
    member_id = None
    class Model(ScriptedModelProvider):
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                settings = await service.get_settings()
                await service.save_settings(settings.model_copy(update={"component_configs": {
                    **settings.component_configs, "execution.sandbox": {"resources": {"disk_mb": 1}}}}))
                value = step(ModelToolCall(tool_call_id="delegate", name="sys_team_delegate_task", arguments={
                    "tasks": [{"agent_id": member_id, "content": "Review"}]}))
            else:
                value = step()
            for event in value.events:
                yield event
    service, _, environments = desktop(tmp_path, model=Model(()))
    try:
        settings = await service.get_settings()
        await service.save_settings(settings.model_copy(update={"component_configs": {
            **settings.component_configs, "execution.sandbox": {"resources": {"disk_mb": 32768}}}}))
        await service.list_agents("user_1")
        member = await service.create_agent(AgentCreate(name="Quota Reviewer"), "user_1")
        member_id = member["id"]
        await service.patch_agent_settings("sage", AgentSettingsPatch(agent_mode="team", sub_agent_selection_mode="manual", available_sub_agent_ids=[member_id]), "user_1")
        run, _, _ = await execute(service, request=DesktopRunRequest(agent_id="sage", messages=[RunMessage(role="user", text="Review")], approval_mode="auto_approve"))
        assert run.state.value == "completed"
        assert len(environments) == 2
        for environment in environments:
            snapshot = await service.application.execution_configuration(environment.run_id, service._context("user_1"))
            assert snapshot.policy["resources"]["disk_mb"] == 32768
            assert snapshot.policy["filesystem"]["max_total_bytes"] == 32768 * 1024**2
        later, _, _ = await execute(service)
        assert later.state.value == "completed"
        snapshot = await service.application.execution_configuration(later.run_id, service._context("user_1"))
        assert snapshot.policy["resources"]["disk_mb"] == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_desktop_start_automatically_recovers_delayed_run_after_restart(tmp_path, monkeypatch):
    import asyncio
    from sagents.v2.agent.engine import AgentLoopEngine
    from sagents.v2.contracts.run_state import RunState

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.5)
    first_model = ScriptedModelProvider((ScriptedModelStep(events=(), error=RuntimeErrorInfo(
        code="model.provider_transient", category=ErrorCategory.PROVIDER_TRANSIENT,
        message="offline", retryable=True,
    )),))
    service = DesktopV2Service(tmp_path)

    async def offline_model(*args, **kwargs):
        return first_model

    monkeypatch.setattr(service, "_model_provider", offline_model)
    await service.list_agents("user_1")
    settings = await service.get_settings()
    await service.save_settings(settings.model_copy(update={"component_selections": {
        **settings.component_selections,
        "agent.continuation-policy": "sage.agent.continuation.deterministic",
    }}))
    await service.patch_model_provider("model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1")
    await service.patch_agent_settings("sage", AgentSettingsPatch(
        agent_mode="simple", available_tools=[], available_skills=[],
    ), "user_1")
    stream = service.run_events(DesktopRunRequest(
        agent_id="sage", messages=[RunMessage(role="user", text="finish work")],
        idempotency_key="desktop-autonomous-restart",
    ), "user_1")
    run_id = None
    try:
        async def until_waiting():
            nonlocal run_id
            async for line in stream:
                event = json.loads(line)
                if event.get("kind") == "stream.opened":
                    run_id = event["handle"]["run_id"]
                if event.get("type") == "step.retry_scheduled":
                    return
        await asyncio.wait_for(until_waiting(), 5)
        await stream.aclose()
        await service.close()

        restored_model = ScriptedModelProvider((ScriptedModelStep(events=(ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(response_id="recovered", text="done", finish_reason="stop"),
        ),)),))
        restored = DesktopV2Service(tmp_path)

        async def online_model(*args, **kwargs):
            return restored_model

        monkeypatch.setattr(restored, "_model_provider", online_model)
        try:
            await restored.start()
            async def completed():
                while (run := await restored.runtime.get_run(run_id)).state != RunState.COMPLETED:
                    assert run.state != RunState.FAILED
                    await asyncio.sleep(0.01)
                return run
            await asyncio.wait_for(completed(), 5)
            assert len(restored_model.requests) == 1
            assert not [e for e in await restored.session_store.read_events(run_id) if e.type == "run.failed"]
        finally:
            await restored.close()
    finally:
        await stream.aclose()
        await service.close()


@pytest.mark.asyncio
async def test_desktop_recovers_repeated_outages_without_reusing_closed_bindings(tmp_path, monkeypatch):
    import asyncio
    from sagents.v2.agent.engine import AgentLoopEngine

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.02)
    failure = ScriptedModelStep(events=(), error=RuntimeErrorInfo(
        code="model.provider_transient", category=ErrorCategory.PROVIDER_TRANSIENT,
        message="offline", retryable=True,
    ))
    model = ScriptedModelProvider((failure, failure, ScriptedModelStep(events=(ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(response_id="recovered", text="done", finish_reason="stop"),
    ),))))
    service = DesktopV2Service(tmp_path)
    async def provider(*args, **kwargs):
        return model
    monkeypatch.setattr(service, "_model_provider", provider)
    try:
        settings = await service.get_settings()
        await service.save_settings(settings.model_copy(update={"component_selections": {
            **settings.component_selections,
            "agent.continuation-policy": "sage.agent.continuation.deterministic",
        }}))
        await service.list_agents("user_1")
        await service.patch_model_provider("model_main", ModelProviderPatch(api_keys=["test-key"]), "user_1")
        await service.patch_agent_settings("sage", AgentSettingsPatch(
            agent_mode="simple", available_tools=[], available_skills=[],
        ), "user_1")
        async def collect():
            return [json.loads(line) async for line in service.run_events(DesktopRunRequest(
                agent_id="sage", messages=[RunMessage(role="user", text="finish")],
                idempotency_key="repeated-outage",
            ), "user_1")]
        events = await asyncio.wait_for(collect(), 5)
        assert any(e.get("type") == "run.completed" for e in events)
        assert not any(e.get("type") in {"interaction.requested", "run.failed"} for e in events)
        assert len(model.requests) == 3
    finally:
        await service.close()
