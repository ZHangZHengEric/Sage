"""One composition root for CLI, tests, or an embedding HTTP/UI application."""

from dataclasses import dataclass
from pathlib import Path

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.runtime import RuntimeConfig
from .plugins import estimator_registration
from sagents.v2.package.manifest import SageManifestLoader
from sagents.v2.runtime.observability import FilesystemDiagnosticSink, StdoutLogSink


@dataclass(frozen=True)
class HostSettings:
    manifest_path: Path
    runtime_root: Path
    log_level: str = "info"
    environment: str | None = None
    runtime: RuntimeConfig | None = None


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
    builder = (
        SAgentBuilder()
        .with_defaults(session_root=runtime_root)
        .with_log_sink(StdoutLogSink(stream="stderr", min_level=settings.log_level))
        .with_diagnostic_sink(FilesystemDiagnosticSink(runtime_root / "sessions"))
        .with_readiness_check()
    )
    for registration in (estimator_registration(), *extensions):
        builder.register(registration)
    if model is not None:
        builder.with_model_provider(model)
    return await builder.build(manifest, runtime=settings.runtime)
