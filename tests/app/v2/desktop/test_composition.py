from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.v2.desktop.backend.bindings import DesktopExecutionBindingProvider
from app.v2.desktop.backend.composition import build_desktop_application
from app.v2.desktop.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS,
    desktop_v2_manifest,
)
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.agent.multi_agent import WorkspaceSharingPolicy
from sagents.v2.contracts.commands import RunConfig, StartRun
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


async def _acquire_accepted(bindings, request):
    """Exercise the binding contract with admission preceding resource creation."""
    command = await bindings.accept_configuration(StartRun(
        agent_id=request.agent_id, input=(), resolved_spec_hash="test-composition",
        idempotency_key=request.run_id, parent_run_id=request.parent_run_id,
        config=RunConfig(metadata={"workspace_policy": getattr(request.workspace_policy, "value", request.workspace_policy)}),
    ), context=request.context)
    return await bindings.acquire(replace(
        request, configuration=command.config.execution_snapshot,
    ))


def test_desktop_manifest_encodes_product_defaults(tmp_path: Path):
    manifest = desktop_v2_manifest(session_root=tmp_path)
    capabilities = manifest.runtime.capabilities

    assert manifest.metadata.id == "com.sage.desktop-v2"
    assert "credentials" not in manifest.model_dump()
    assert "models" not in manifest.model_dump()
    assert (
        capabilities["session.store"].plugin
        == DESKTOP_COMPONENT_DEFAULTS["session.store"]
    )
    assert (
        capabilities["memory.provider"].plugin
        == (DESKTOP_COMPONENT_DEFAULTS["memory.provider"])
    )
    assert (
        capabilities["session-memory.provider"].plugin
        == (DESKTOP_COMPONENT_DEFAULTS["session-memory.provider"])
    )
    assert (
        capabilities["workspace.initializer"].plugin
        == (DESKTOP_COMPONENT_DEFAULTS["workspace.initializer"])
    )
    assert (
        capabilities["agent.continuation-policy"].plugin
        == (DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"])
    )
    assert (
        capabilities["memory.recall-query"].plugin
        == (DESKTOP_COMPONENT_DEFAULTS["memory.recall-query"])
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
    assert "context.token-estimator" not in capabilities
    assert (
        capabilities["agent.continuation-policy"].plugin
        == "sage.agent.continuation.llm-judge"
    )


@pytest.mark.asyncio
async def test_desktop_binding_provisions_a_run_owned_sandbox(tmp_path: Path):
    workspace = tmp_path / "workspace"
    bindings = DesktopExecutionBindingProvider(workspace)
    binding = await _acquire_accepted(bindings,
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
    shared = await _acquire_accepted(bindings,
        ExecutionBindingRequest(
            run_id="run_shared",
            agent_id="main",
            context=context,
            workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
        )
    )
    private = await _acquire_accepted(bindings,
        ExecutionBindingRequest(
            run_id="run_private",
            parent_run_id="run_shared",
            agent_id="member",
            context=context,
            workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        )
    )
    read_only = await _acquire_accepted(bindings,
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
    assert read_only_row.spec.process.read_only is True

    await bindings.close()

    assert shared.closed is True
    assert private.closed is True
    assert read_only.closed is True
    with pytest.raises(RuntimeError, match="provider is closed"):
        await _acquire_accepted(bindings,
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
        for capability in ("observability.log-sink", "observability.diagnostic-sink", "model.provider"):
            binding = _provider(plan, capability)
            assert binding.source == "plugin"
            assert binding.plugin_id == "com.sage.desktop." + capability.replace(".", "-")
        assert (
            _provider(plan, "memory.provider").plugin_id
            == (DESKTOP_COMPONENT_DEFAULTS["memory.provider"])
        )
        assert (
            _provider(plan, "session-memory.provider").plugin_id
            == (DESKTOP_COMPONENT_DEFAULTS["session-memory.provider"])
        )
        assert (
            _provider(plan, "workspace.initializer").plugin_id
            == (DESKTOP_COMPONENT_DEFAULTS["workspace.initializer"])
        )
        assert (
            _provider(plan, "agent.continuation-policy").plugin_id
            == (DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"])
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
        assert service.dispatcher is service.application.service("execution.dispatcher")
        assert service.memory_provider is service.application.service("memory.provider")
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


def test_core_document_read_limit_cannot_hide_instructions_after_whitespace(tmp_path):
    from app.v2.desktop.backend.run_composition import DesktopRunCompositionMixin
    from sagents.v2.contracts.errors import SageV2Error

    (tmp_path / "AGENT.md").write_text(
        "x" * 16000 + "\nMust preserve this constraint.", encoding="utf-8"
    )
    with pytest.raises(SageV2Error) as caught:
        DesktopRunCompositionMixin()._identity_documents(tmp_path)
    assert caught.value.info.code == "context.system_document_too_large"


def test_shell_network_configuration_changes_binding_fingerprint(tmp_path):
    from app.v2.desktop.backend.runtime_config import _sandbox_network_policy

    offline = DesktopExecutionBindingProvider(tmp_path / "workspace")
    online = DesktopExecutionBindingProvider(
        tmp_path / "workspace",
        network=_sandbox_network_policy({"mode": "unrestricted"}),
    )
    assert offline.sandbox_spec().network.mode.value == "none"
    assert online.sandbox_spec().network.mode.value == "unrestricted"
    assert online.sandbox_spec().network.deny_private_networks is False
    assert offline.sandbox_spec().spec_hash != online.sandbox_spec().spec_hash


def test_desktop_resolves_shell_network_setting():
    from app.v2.desktop.backend.runtime_config import _resolved_sandbox_config
    from app.v2.desktop.backend.schemas import DesktopV2Settings

    _, config = _resolved_sandbox_config(
        DesktopV2Settings(
            component_configs={
                "execution.sandbox": {"network": {"mode": "unrestricted"}}
            }
        )
    )
    assert config["network"]["mode"] == "unrestricted"
    assert config["network"]["deny_private_networks"] is False


@pytest.mark.parametrize("network", [
    {"mode": "allowlist", "allowed_hosts": ["example.com"]},
    {"mode": "proxy", "proxy_url": "http://localhost:8080"},
])
def test_desktop_resolves_proxy_network_configuration(network):
    from app.v2.desktop.backend.runtime_config import _resolved_sandbox_config
    from app.v2.desktop.backend.schemas import DesktopV2Settings

    _, config = _resolved_sandbox_config(DesktopV2Settings(component_configs={"execution.sandbox": {"network": network}}))
    assert config["network"]["mode"] == network["mode"]
    assert config["network"]["deny_private_networks"] is True
    assert config["network"]["allowed_schemes"] == ["http", "https"]


@pytest.mark.parametrize("saved,frozen,expected", [
    ({}, None, "host"),
    ({"workspace_root": "/project"}, None, "virtual"),
    ({}, "virtual", "virtual"),
    ({}, "host", "host"),
    ({"workspace_path_mode": "virtual"}, "host", "virtual"),
    ({"workspace_path_mode": "host"}, "virtual", "host"),
])
def test_workspace_path_default_preserves_explicit_and_frozen_configuration(saved, frozen, expected):
    from app.v2.desktop.backend.runtime_config import _resolved_sandbox_config
    from app.v2.desktop.backend.schemas import DesktopV2Settings

    _, config = _resolved_sandbox_config(
        DesktopV2Settings(component_configs={"execution.sandbox": saved}),
        frozen_path_mode=frozen,
    )
    assert config["workspace_path_mode"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("disk_mb", [1, 32768])
async def test_disk_quota_is_consistent_for_all_desktop_workspace_bindings(tmp_path, disk_mb):
    from sagents.v2.runtime.execution.sandbox import ResourceLimits

    bindings = DesktopExecutionBindingProvider(
        tmp_path / "workspace", resources=ResourceLimits(disk_mb=disk_mb, require_hard_limits=False),
    )
    try:
        await _acquire_accepted(bindings, ExecutionBindingRequest(
            run_id="parent", agent_id="parent", context=_context(),
        ))
        for index, policy in enumerate(WorkspaceSharingPolicy):
            binding = await _acquire_accepted(bindings, ExecutionBindingRequest(
                run_id=f"quota-{index}", parent_run_id="parent", agent_id="member",
                context=_context(), workspace_policy=policy,
            ))
            try:
                spec = binding.sandbox.provider._row(binding.sandbox.ref).spec
                assert spec.resources.disk_mb == disk_mb
                assert spec.filesystem.max_total_bytes == disk_mb * 1024**2
            finally:
                await binding.close()
    finally:
        await bindings.close()


@pytest.mark.asyncio
async def test_workspace_larger_than_four_gib_can_write_under_configured_quota(tmp_path):
    from sagents.v2.runtime.execution.sandbox import OperationIntent, ResourceLimits

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Sparse fixture exercises logical quota accounting without writing 5 GiB.
    with (workspace / "existing-video.mp4").open("wb") as artifact:
        artifact.truncate(5 * 1024**3)
    bindings = DesktopExecutionBindingProvider(
        workspace, resources=ResourceLimits(disk_mb=32768, require_hard_limits=False),
    )
    try:
        binding = await _acquire_accepted(bindings, ExecutionBindingRequest(
            run_id="large-workspace", agent_id="main", context=_context(),
            workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
        ))
        path = str(workspace / "result.txt")
        intent = OperationIntent(
            operation="create", run_id=binding.run_id, tool_call_id="write-result",
            sandbox_id=binding.sandbox.ref.sandbox_id, path=path,
        )
        grant = bindings.issuer.issue(
            ref=binding.sandbox.ref, intent=intent, allowed_operations=frozenset({"create"}),
        )
        await binding.sandbox.filesystem.write_bytes(path, b"done", intent=intent, grant=grant)
        assert (workspace / "result.txt").read_bytes() == b"done"
    finally:
        await bindings.close()
