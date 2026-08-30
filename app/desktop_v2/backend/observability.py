"""Desktop composition for the replaceable structured log sink capability."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.runtime.observability import FilesystemLogSink, LogSink


DEFAULT_LOG_PLUGIN = "sage.logging.filesystem"
LOG_CAPABILITY = "observability.log-sink"


def create_desktop_log_sink(runtime_root: Path) -> tuple[str, LogSink]:
    selected = DEFAULT_LOG_PLUGIN
    settings_path = runtime_root / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        selections = settings.get("component_selections") or settings.get(
            "componentSelections"
        )
        if isinstance(selections, dict):
            candidate = selections.get(LOG_CAPABILITY)
            if isinstance(candidate, str) and candidate.strip():
                selected = candidate.strip()
    except (OSError, ValueError, AttributeError):
        pass

    registry = builtin_extension_registry()
    try:
        registration = registry.get(selected)
        if LOG_CAPABILITY not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(f"{selected!r} is not a structured log sink")
        value = registration.factory(
            ExtensionScopeContext(
                scope=ExtensionScope.PROCESS,
                scope_id="desktop-v2",
                config={
                    "root": str(runtime_root / "logs"),
                    "filename": "sage.jsonl",
                    "max_bytes": 10 * 1024 * 1024,
                    "backup_count": 5,
                    "min_level": "info",
                },
            ),
            {},
        )
        if inspect.isawaitable(value):
            raise TypeError("Desktop log sink factories must be synchronous")
        return selected, value
    except Exception:
        # Startup logging must remain available even if a persisted optional
        # plugin selection was removed or became unavailable.
        return DEFAULT_LOG_PLUGIN, FilesystemLogSink(runtime_root / "logs")
