"""Official Session-memory provider registrations."""

from __future__ import annotations

from sagents.v2.runtime.extensions.contracts import ExtensionScope
from sagents.v2.runtime.extensions.registration import (
    register_plugin,
    root_config_schema,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.session_memory import (
    NoopSessionMemoryProvider,
    SqliteBm25SessionMemoryProvider,
)


def register_session_memory_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        NoopSessionMemoryProvider,
        "session-memory.provider",
        lambda context, dependencies: NoopSessionMemoryProvider(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )

    register_plugin(
        registry,
        SqliteBm25SessionMemoryProvider,
        "session-memory.provider",
        lambda context, dependencies: SqliteBm25SessionMemoryProvider(
            context.config["root"]
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema=root_config_schema(),
    )
