"""One composition root for CLI, tests, or an embedding HTTP/UI application."""

from dataclasses import dataclass
from pathlib import Path

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.runtime import RuntimeConfig
from .plugins import compactor_registration
from sagents.v2.package.manifest import SageManifestLoader


@dataclass(frozen=True)
class HostSettings:
    manifest_path: Path
    runtime_root: Path
    log_level: str = "info"
    environment: str | None = None
    runtime: RuntimeConfig | None = None
    models: object | None = None


async def build_application(
    settings: HostSettings,
    *,
    model: ModelProvider | None = None,
    extensions=(),
) -> SAgentApplication:
    """Inject host ports here; request handlers must not assemble plugins."""
    manifest = SageManifestLoader().load(
        settings.manifest_path,
        environment=settings.environment,
    )
    runtime_root = settings.runtime_root.expanduser().resolve()
    from .registrations import provided
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    builder = SAgentBuilder()
    runtime = settings.runtime if settings.runtime is not None else manifest.runtime
    capabilities = {**runtime.capabilities,
        "session.store": CapabilitySelection(plugin="sage.session.filesystem", config={"root": str(runtime_root)}),
        "observability.log-sink": CapabilitySelection(plugin="sage.logging.stdout", config={"stream": "stderr", "min_level": settings.log_level}),
        "observability.diagnostic-sink": CapabilitySelection(plugin="sage.observability.filesystem", config={"root": str(runtime_root / "sessions")}),
    }
    for registration in (compactor_registration(), *extensions):
        builder.register(registration)
    if model is not None:
        builder.register(provided("example.host.model", lambda context, deps: model, "model.provider"))
        capabilities["model.provider"] = CapabilitySelection(plugin="example.host.model")
    runtime = runtime.model_copy(update={"capabilities": capabilities, "state_root": str(runtime_root), "check_readiness": True})
    app = await builder.build(runtime=runtime, models=settings.models if settings.models is not None else settings.manifest_path.with_name("models.yaml"))
    try:
        await app.load_agent(manifest)
    except BaseException:
        await app.close()
        raise
    return app
