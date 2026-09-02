"""Build Desktop's process Application through ``SAgentBuilder`` only."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.model import ModelProvider
from sagents.v2.model.contracts import ModelCapabilities
from sagents.v2.runtime.observability import DiagnosticSink, LogSink
from sagents.v2.runtime.session import SessionStore

from app.desktop_v2.backend.bindings import DesktopExecutionBindingProvider
from app.desktop_v2.backend.package import desktop_v2_manifest


class UnusableProcessModelProvider:
    """Placeholder so the process Application can build before a catalog model exists."""

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        del model_binding
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    async def stream(self, request):
        del request
        raise RuntimeError("Desktop process Application model is a composition placeholder")
        yield


async def build_desktop_application(
    *,
    session_root: str | Path,
    workspace: str | Path,
    model_provider: ModelProvider | None = None,
    log_sink: LogSink | None = None,
    diagnostic_sink: DiagnosticSink | None = None,
    session_store: SessionStore | None = None,
    component_selections: Mapping[str, str] | None = None,
    component_configs: Mapping[str, Mapping[str, Any]] | None = None,
    language: str = "en",
    bindings: DesktopExecutionBindingProvider | None = None,
) -> SAgentApplication:
    """Assemble Desktop runtime as Manifest + host bindings.

    Catalog, session index, and MCP records are not composition inputs.
    """

    root = Path(session_root).expanduser().resolve()
    workspace_path = Path(workspace).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    provider = bindings or DesktopExecutionBindingProvider(workspace_path)
    builder = (
        SAgentBuilder()
        .with_defaults(session_root=root)
        .with_model_provider(model_provider or UnusableProcessModelProvider())
        .with_execution_binding_provider(provider)
    )
    if session_store is not None:
        builder = builder.with_session_store(session_store).with_derived_state_store(
            session_store
        )
    if log_sink is not None:
        builder = builder.with_log_sink(log_sink)
    if diagnostic_sink is not None:
        builder = builder.with_diagnostic_sink(diagnostic_sink)
    return await builder.build(
        desktop_v2_manifest(
            session_root=root,
            component_selections=component_selections,
            component_configs=component_configs,
            language=language,
        )
    )
