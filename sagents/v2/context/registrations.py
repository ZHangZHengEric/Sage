"""Official context reducer, summary-store and summarizer registrations."""

from __future__ import annotations

from sagents.v2.context import (
    ExtractiveConversationSummarizer,
    InMemoryConversationSummaryStore,
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
    SessionDerivedConversationSummaryStore,
    WindowContextReducer,
)
from sagents.v2.context.plugins.summarizer_model import (
    DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS,
)
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.runtime.extensions.contracts import ExtensionDependency, ExtensionScope
from sagents.v2.runtime.extensions.registration import register_plugin
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_context_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        WindowContextReducer,
        "context.reducer",
        lambda context, dependencies: WindowContextReducer(),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={"type": "object", "additionalProperties": False},
    )

    register_plugin(
        registry,
        PersistentSummaryContextReducer,
        "context.reducer",
        lambda context, dependencies: PersistentSummaryContextReducer(
            dependencies.require_unique("context.summary-store"),
            summarizer=dependencies.require_unique("context.summarizer"),
            summary_target_tokens=int(
                context.config.get("summary_target_tokens", 1024)
            ),
            protected_recent_units=int(context.config.get("protected_recent_units", 4)),
            max_summary_calls=int(context.config.get("max_summary_calls", 64)),
        ),
        dependencies=(
            ExtensionDependency(capability="context.summary-store"),
            ExtensionDependency(capability="context.summarizer"),
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={
            "type": "object",
            "properties": {
                "summary_target_tokens": {"type": "integer", "minimum": 1},
                "protected_recent_units": {"type": "integer", "minimum": 1},
                "max_summary_calls": {"type": "integer", "minimum": 1},
                "max_summary_source_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 24_000,
                },
            },
            "additionalProperties": False,
        },
    )

    register_plugin(
        registry,
        InMemoryConversationSummaryStore,
        "context.summary-store",
        lambda context, dependencies: InMemoryConversationSummaryStore(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )

    register_plugin(
        registry,
        SessionDerivedConversationSummaryStore,
        "context.summary-store",
        lambda context, dependencies: SessionDerivedConversationSummaryStore(
            dependencies.require_unique("derived-state.store")
        ),
        dependencies=(ExtensionDependency(capability="derived-state.store"),),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema={
            "type": "object",
            "additionalProperties": False,
        },
    )

    register_plugin(
        registry,
        ExtractiveConversationSummarizer,
        "context.summarizer",
        lambda context, dependencies: ExtractiveConversationSummarizer(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )

    register_plugin(
        registry,
        ModelConversationSummarizer,
        "context.summarizer",
        lambda context, dependencies: ModelConversationSummarizer(
            dependencies.require_unique("model.provider"),
            model_binding=str(context.config.get("model_binding", "primary")),
            max_source_tokens=int(context.config.get("max_source_tokens", 24000)),
            timeout_seconds=float(
                context.config.get(
                    "timeout_seconds", DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS
                )
            ),
            idle_timeout_seconds=float(
                context.config.get(
                    "idle_timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                )
            ),
        ),
        dependencies=(ExtensionDependency(capability="model.provider"),),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={
            "type": "object",
            "properties": {
                "model_binding": {
                    "type": "string",
                    "const": "primary",
                    "default": "primary",
                    "readOnly": True,
                },
                "max_source_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 24_000,
                },
                "timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS,
                },
                "idle_timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                },
            },
            "additionalProperties": False,
        },
        capabilities={"uses_model": True, "bounded_timeout": True},
    )
