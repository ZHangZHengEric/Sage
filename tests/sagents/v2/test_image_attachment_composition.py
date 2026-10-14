"""Exercise image attachment wiring through the public builder and host loops."""

from pathlib import Path

import pytest
from PIL import Image

from sagents.v2 import RunExecutionBinding, SAgentBuilder
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    ProcessPolicy,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxGrantIssuer,
)
from sagents.v2.runtime.artifact import ScopedArtifactStore, FilesystemArtifactStore
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)


@pytest.mark.asyncio
async def test_builder_wires_durable_images_from_tool_to_request_and_session(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    Image.new("RGB", (32, 32), "red").save(workspace / "frame.png")
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)

    class Bindings:
        async def acquire(self, request):
            handle = await provider.provision(
                ResolvedSandboxSpec(
                    resources=ResourceLimits(require_hard_limits=False),
                    spec_hash="sha256:image",
                    architecture="native",
                    filesystem=FileSystemPolicy(
                        allowed_operations=frozenset(FileOperation)
                    ),
                    process=ProcessPolicy(enabled=False),
                    policy_hash="sha256:image",
                    metadata={"host_workspace": str(workspace)},
                ),
                request.context,
                run_id=request.run_id,
            )
            return RunExecutionBinding(
                run_id=request.run_id,
                agent_id=request.agent_id,
                workspace_root=str(workspace),
                workspace_policy=request.workspace_policy,
                sandbox=handle,
                grant_issuer=issuer,
            )

    def completed(response_id, **kwargs):
        return ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id=response_id, finish_reason="stop", **kwargs
                    ),
                ),
            )
        )

    model = ScriptedModelProvider(
        (
            completed(
                "attach",
                tool_calls=(
                    ModelToolCall(
                        tool_call_id="image_call",
                        name="analyze_image",
                        arguments={
                            "image_path": "/workspace/frame.png",
                            "session_id": "ignored",
                            "prompt": "Inspect",
                        },
                    ),
                ),
            ),
            completed("done", text="done"),
        )
    )
    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.durable-images",
        model="test-model",
    )
    agent_id = package.entrypoint.agent
    package = package.model_copy(
        update={
            "agents": {
                agent_id: package.agents[agent_id].model_copy(
                    update={"tools": ("analyze_image",)}
                )
            },
            "runtime": package.runtime.model_copy(
                update={
                    "capabilities": {
                        **package.runtime.capabilities,
                        "tool.catalog": CapabilitySelection(
                            plugin="sage.tool.official", name="official"
                        ),
                        "tool.selection-policy": CapabilitySelection(
                            plugin="sage.tool-selection.direct"
                        ),
                    }
                }
            ),
        }
    )
    root = tmp_path / "sessions"
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=root)
        .with_model_provider(model)
        .with_execution_binding_provider(Bindings())
        .build(package)
    )
    try:
        assert isinstance(application.service("artifact.store"), FilesystemArtifactStore)
        stream = await application.entrypoint().run_stream(
            StartRun(
                agent_id=agent_id,
                input=(
                    InputItem(role="user", content=(TextBlock(text="inspect image"),)),
                ),
                resolved_spec_hash=application.composition_hash,
                idempotency_key="image-run",
            ),
            RequestContext(
                actor=ActorRef(
                    principal_id="owner",
                    principal_type=PrincipalType.USER,
                    tenant_id="tenant",
                )
            ),
        )
        run = await stream.wait()
        assert run.state == RunState.COMPLETED
        images = [
            block
            for message in model.requests[-1].messages
            for block in message.content
            if isinstance(block, ImageBlock)
        ]
        assert len(images) == 1
        assert images[0].uri.startswith("data:image/jpeg;base64,")
        events = await application.entrypoint().runtime.session_store.read_events(
            run.run_id
        )
        import json

        serialized = json.dumps([event.model_dump(mode="json") for event in events])
        assert "sage-image:" in serialized
        assert "data:image" not in serialized
        # Reopen the host store in the namespace selected from the Run's tenant.
        digest = images[0].uri.split(",", 1)[1]
        import base64
        import hashlib

        identifier = hashlib.sha256(base64.b64decode(digest)).hexdigest()
        reference, _ = await ScopedArtifactStore(
            FilesystemArtifactStore(root / "artifacts"), "tenant"
        ).get(identifier)
        assert reference.digest == "sha256:" + identifier
    finally:
        await application.close()
