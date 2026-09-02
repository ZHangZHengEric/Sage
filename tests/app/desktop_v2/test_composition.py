from __future__ import annotations

from pathlib import Path

import pytest

from app.desktop_v2.backend.bindings import DesktopExecutionBindingProvider
from app.desktop_v2.backend.composition import build_desktop_application
from app.desktop_v2.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS,
    desktop_v2_manifest,
)
from app.desktop_v2.backend.service import DesktopV2Service
from sagents.v2.agent.multi_agent import WorkspaceSharingPolicy
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution import ExecutionBindingRequest
from sagents.v2.runtime.observability import NoopDiagnosticSink, NoopLogSink
from sagents.v2.runtime.session import EphemeralSessionStore, InMemoryDerivedStateStore
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider


def _context() -> RequestContext:
    return RequestContext(
        actor=ActorRef(
            principal_id="user_1",
            principal_type=PrincipalType.USER,
            tenant_id="desktop",
        )
    )


def test_desktop_manifest_encodes_product_defaults(tmp_path: Path):
    manifest = desktop_v2_manifest(session_root=tmp_path)
    capabilities = manifest.runtime.capabilities

    assert manifest.metadata.id == "com.sage.desktop-v2"
    assert manifest.credentials == {}
    assert manifest.models == {}
    assert capabilities["session.store"].plugin == DESKTOP_COMPONENT_DEFAULTS[
        "session.store"
    ]
    assert capabilities["memory.provider"].plugin == (
        DESKTOP_COMPONENT_DEFAULTS["memory.provider"]
    )
    assert capabilities["session-memory.provider"].plugin == (
        DESKTOP_COMPONENT_DEFAULTS["session-memory.provider"]
    )
    assert capabilities["workspace.initializer"].plugin == (
        DESKTOP_COMPONENT_DEFAULTS["workspace.initializer"]
    )
    assert capabilities["agent.continuation-policy"].plugin == (
        DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"]
    )
    assert capabilities["memory.recall-query"].plugin == (
        DESKTOP_COMPONENT_DEFAULTS["memory.recall-query"]
    )
    assert "execution.sandbox" not in capabilities
    assert capabilities["memory.provider"].config["root"] == str(tmp_path / "memory")


def test_desktop_manifest_applies_user_component_selections(tmp_path: Path):
    manifest = desktop_v2_manifest(
        session_root=tmp_path,
        component_selections={
            "context.token-estimator": "sage.context.token-estimator.unicode-heuristic",
            "agent.continuation-policy": "hybrid",
        },
    )
    capabilities = manifest.runtime.capabilities
    assert (
        capabilities["context.token-estimator"].plugin
        == "sage.context.token-estimator.unicode-heuristic"
    )
    assert (
        capabilities["agent.continuation-policy"].plugin
        == "sage.agent.continuation.llm-judge"
    )


@pytest.mark.asyncio
async def test_desktop_binding_provisions_a_run_owned_sandbox(tmp_path: Path):
    workspace = tmp_path / "workspace"
    bindings = DesktopExecutionBindingProvider(workspace)
    binding = await bindings.acquire(
        ExecutionBindingRequest(
            run_id="run_1",
            agent_id="main",
            context=_context(),
        )
    )
    try:
        assert binding.run_id == "run_1"
        assert binding.sandbox.ref.owner_run_id == "run_1"
        assert binding.grant_issuer is bindings.issuer
        assert Path(binding.workspace_root) == workspace.resolve()
    finally:
        await binding.close()


@pytest.mark.asyncio
async def test_desktop_binding_enforces_workspace_sharing_policy(tmp_path: Path):
    workspace = tmp_path / "workspace"
    private_root = tmp_path / "private"
    bindings = DesktopExecutionBindingProvider(
        workspace,
        private_workspace_root=private_root,
    )
    context = _context()
    shared = await bindings.acquire(
        ExecutionBindingRequest(
            run_id="run_shared",
            agent_id="main",
            context=context,
            workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
        )
    )
    private = await bindings.acquire(
        ExecutionBindingRequest(
            run_id="run_private",
            parent_run_id="run_shared",
            agent_id="member",
            context=context,
            workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        )
    )
    read_only = await bindings.acquire(
        ExecutionBindingRequest(
            run_id="run_read_only",
            parent_run_id="run_shared",
            agent_id="reviewer",
            context=context,
            workspace_policy=WorkspaceSharingPolicy.READ_ONLY_PARENT,
        )
    )

    assert Path(shared.workspace_root) == workspace.resolve()
    assert Path(private.workspace_root).parent == private_root.resolve()
    assert private.workspace_root != shared.workspace_root
    private.validate_for(
        ExecutionBindingRequest(
            run_id="run_private",
            parent_run_id="run_shared",
            agent_id="member",
            context=context,
            workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        )
    )
    read_only_row = bindings.sandbox_provider._rows[read_only.sandbox.ref.sandbox_id]
    assert read_only.workspace_root == shared.workspace_root
    assert read_only_row.spec.filesystem.allowed_operations == frozenset(
        {"read", "list"}
    )
    assert read_only_row.spec.process.enabled is False

    await bindings.close()

    assert shared.closed is True
    assert private.closed is True
    assert read_only.closed is True
    with pytest.raises(RuntimeError, match="provider is closed"):
        await bindings.acquire(
            ExecutionBindingRequest(
                run_id="run_after_close",
                agent_id="main",
                context=context,
            )
        )


def test_desktop_binding_rejects_private_root_inside_shared_workspace(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    with pytest.raises(ValueError, match="outside the shared workspace"):
        DesktopExecutionBindingProvider(
            workspace,
            private_workspace_root=workspace / ".private",
        )


class _AuthoritativeOnlySessionStore:
    def __init__(self) -> None:
        self.store = EphemeralSessionStore()

    def __getattr__(self, name):
        if name in {
            "get_derived_state",
            "put_derived_state",
            "delete_derived_state",
            "forget_session",
        }:
            raise AttributeError(name)
        return getattr(self.store, name)


@pytest.mark.asyncio
async def test_desktop_composition_keeps_session_and_derived_stores_separate(
    tmp_path: Path,
):
    session_store = _AuthoritativeOnlySessionStore()
    application = await build_desktop_application(
        session_root=tmp_path / "runtime",
        workspace=tmp_path / "workspace",
        model_provider=ScriptedModelProvider(()),
        session_store=session_store,
    )
    try:
        assert application.entrypoint().runtime.session_store is session_store
        assert isinstance(
            application.service("derived-state.store"), InMemoryDerivedStateStore
        )
    finally:
        await application.close()


def _provider(plan, capability: str):
    return next(value for value in plan.providers if value.capability == capability)


@pytest.mark.asyncio
async def test_desktop_builder_path_exposes_a_real_resolved_plan(tmp_path: Path):
    log_sink = NoopLogSink()
    diagnostic_sink = NoopDiagnosticSink()
    application = await build_desktop_application(
        session_root=tmp_path / "runtime",
        workspace=tmp_path / "workspace",
        model_provider=ScriptedModelProvider(()),
        log_sink=log_sink,
        diagnostic_sink=diagnostic_sink,
    )
    try:
        plan = application.resolved_plan
        sources = {value.source for value in plan.providers}
        assert "desktop-host" not in sources
        assert application.service("observability.log-sink") is log_sink
        assert application.service("observability.diagnostic-sink") is diagnostic_sink
        assert _provider(plan, "observability.log-sink").source == "host"
        assert _provider(plan, "observability.diagnostic-sink").source == "host"
        assert _provider(plan, "model.provider").source == "host"
        assert _provider(plan, "memory.provider").plugin_id == (
            DESKTOP_COMPONENT_DEFAULTS["memory.provider"]
        )
        assert _provider(plan, "session-memory.provider").plugin_id == (
            DESKTOP_COMPONENT_DEFAULTS["session-memory.provider"]
        )
        assert _provider(plan, "workspace.initializer").plugin_id == (
            DESKTOP_COMPONENT_DEFAULTS["workspace.initializer"]
        )
        assert _provider(plan, "agent.continuation-policy").plugin_id == (
            DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"]
        )
        assert _provider(plan, "execution.dispatcher").source == "composition-root"
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_desktop_service_process_root_uses_builder_application(tmp_path: Path):
    service = DesktopV2Service(tmp_path)
    assert service.application is None
    assert not hasattr(service, "_process_component")
    await service.start()
    try:
        plan = service.application.resolved_plan
        assert service.dispatcher is service.application.service(
            "execution.dispatcher"
        )
        assert service.memory_provider is service.application.service(
            "memory.provider"
        )
        assert service.diagnostics is service.application.service(
            "observability.diagnostic-sink"
        )
        assert {value.source for value in plan.providers} <= {
            "plugin",
            "host",
            "composition-root",
            "plugin-deferred",
        }
        assert "desktop-host" not in {value.source for value in plan.providers}
    finally:
        await service.close()
