"""Desktop tests exercise actual registered providers and standard Run admission."""

import json

from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.schemas import (
    DesktopRunRequest,
    ModelProviderPatch,
    RunMessage,
)
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from tests.sagents.v2.test_standard_execution_configuration import response
from sagents.v2.testing.plugins import ScriptedModelProvider


def desktop(root, *, model=None, runtime=None, registrations=(), **kwargs):
    provider = model or ScriptedModelProvider(tuple(response() for _ in range(16)))
    created = []

    def create(scope, dependencies):
        run = dependencies.require("execution.environment")
        assert scope.run_id == run.run_id
        assert scope.tenant_id == run.context.actor.tenant_id
        created.append(run)
        return provider

    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.desktop.model",
            name="Desktop model",
            version="1",
            provides=(CapabilityOffer(capability="model.provider", api_version="2"),),
            dependencies=(ExtensionDependency(capability="execution.environment"),),
            supported_scopes=frozenset({ExtensionScope.RUN}),
            config_schema={"type": "object", "additionalProperties": False},
        ),
        factory=create,
        ownership="borrowed",
    )
    selected = {
        "model.provider": {"plugin": "test.desktop.model", "scope": "run"},
        "agent.continuation-policy": {
            "plugin": "sage.agent.continuation.deterministic"
        },
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
        "memory.recall-query": {"plugin": "sage.memory.recall-query.direct"},
    }
    selected.update((runtime or {}).get("capabilities", {}))
    service = DesktopV2Service(
        root,
        extensions=(registration, *registrations),
        runtime=RuntimeConfig.model_validate(
            {**(runtime or {}), "capabilities": selected}
        ),
        **kwargs,
    )
    return service, provider, created


async def execute(service, *, user="user_1", agent_id="sage", request=None):
    await service.list_agents(user)
    await service.patch_model_provider(
        "model_main", ModelProviderPatch(api_keys=["test-key"]), user
    )
    frames = [
        json.loads(frame)
        async for frame in service.run_events(
            request
            or DesktopRunRequest(
                agent_id=agent_id, messages=[RunMessage(role="user", text="Work")]
            ),
            user,
        )
    ]
    assert frames and "handle" in frames[0], frames
    run_id = frames[0]["handle"]["run_id"]
    context = service._context(user)
    run = await service.session_access.get_run(run_id, context)
    command = await service.session_access.get_start_command(run_id, context)
    return run, command, frames


def tracked_binding(root):
    from sagents.v2.runtime.execution.local_binding import (
        LocalWorkspaceExecutionBindingProvider,
    )

    acquired = []

    class Binding(LocalWorkspaceExecutionBindingProvider):
        async def acquire(self, request):
            binding = await super().acquire(request)
            acquired.append(binding)
            return binding

    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.desktop.binding",
            name="Tracked binding",
            version="1",
            provides=(
                CapabilityOffer(capability="execution.binding", api_version="2"),
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
        ),
        factory=lambda context, dependencies: Binding(root),
    )
    return (
        registration,
        {"capabilities": {"execution.binding": {"plugin": "test.desktop.binding"}}},
        acquired,
    )


def step(*calls, text=None, assertion=None):
    from dataclasses import replace

    scripted = response(*calls, text=text or "Done")
    if text is not None:
        event = scripted.events[0]
        scripted = replace(
            scripted,
            events=(
                event.model_copy(
                    update={
                        "response": event.response.model_copy(update={"text": text})
                    }
                ),
            ),
        )
    return replace(scripted, assertion=assertion)


async def completed(service, run_id, *, user="user_1"):
    import asyncio

    async with asyncio.timeout(60):
        while True:
            run = await service.session_access.get_run(run_id, service._context(user))
            if run.state.value in {"completed", "failed", "cancelled"}:
                return run
            await asyncio.sleep(0.02)
