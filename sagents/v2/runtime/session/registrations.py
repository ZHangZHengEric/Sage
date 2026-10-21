"""Official Session storage and derived-state registrations."""

from __future__ import annotations

import importlib.util

from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionAvailability,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import (
    empty_config_schema,
    implementation_identity,
    service_registration,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.runtime.session import (
    EphemeralSessionStore,
    FilesystemSessionStore,
    InMemoryDerivedStateStore,
    MysqlSessionStore,
    RedisMysqlSessionStore,
)


def register_session_plugins(registry: ExtensionRegistry) -> None:
    from sagents.v2.runtime.session.plugins import SESSION_STORAGE_CAPABILITIES

    storage_offers = tuple(
        CapabilityOffer(capability=key, api_version="2")
        for key in SESSION_STORAGE_CAPABILITIES
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(FilesystemSessionStore),
                version="2.1.0",
                provides=storage_offers,
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string", "minLength": 1},
                    },
                    "required": ["root"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": False,
                    "supports_actor_authorization": True,
                    "supports_session_attachments": True,
                    "cross_process_subscribe": False,
                    "transactional_outbox": False,
                    "atomic_session_cas": True,
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: FilesystemSessionStore(
                context.config["root"],
            ),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(MysqlSessionStore),
                version="2.0.0",
                provides=storage_offers,
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "dsn": {"type": "string", "minLength": 1},
                        "table_prefix": {"type": "string"},
                        "max_cached_sessions": {"type": "integer", "minimum": 1},
                        "max_cached_bytes": {"type": "integer", "minimum": 1},
                        "cache_idle_seconds": {"type": "number", "minimum": 0},
                        "max_connections": {"type": "integer", "minimum": 2},
                        "max_pending_connections": {"type": "integer", "minimum": 1},
                        "connection_acquire_timeout_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                        },
                    },
                    "required": ["dsn"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": False,
                    "supports_actor_authorization": True,
                    "supports_session_attachments": True,
                    "cross_process_subscribe": False,
                    "transactional_outbox": False,
                    "atomic_session_cas": True,
                },
                availability=ExtensionAvailability(
                    available=importlib.util.find_spec("aiomysql") is not None,
                    reason=(
                        None
                        if importlib.util.find_spec("aiomysql") is not None
                        else "optional aiomysql package is not installed"
                    ),
                ),
                built_in=True,
            ),
            factory=lambda context, dependencies: MysqlSessionStore(
                str(context.config["dsn"]),
                **{
                    key: context.config[key]
                    for key in (
                        "max_cached_sessions",
                        "max_cached_bytes",
                        "cache_idle_seconds",
                        "max_connections",
                        "max_pending_connections",
                        "connection_acquire_timeout_seconds",
                    )
                    if key in context.config
                },
                table_prefix=(
                    None
                    if "table_prefix" not in context.config
                    else str(context.config.get("table_prefix") or "")
                ),
            ),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(RedisMysqlSessionStore),
                version="3.0.0",
                provides=storage_offers,
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "dsn": {"type": "string", "minLength": 1},
                        "redis_url": {"type": "string", "minLength": 1},
                        "max_cached_sessions": {"type": "integer", "minimum": 1},
                        "max_cached_bytes": {"type": "integer", "minimum": 1},
                        "cache_idle_seconds": {"type": "number", "minimum": 0},
                        "max_connections": {"type": "integer", "minimum": 2},
                        "max_pending_connections": {"type": "integer", "minimum": 1},
                        "connection_acquire_timeout_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                        },
                        "table_prefix": {"type": "string"},
                        "key_prefix": {"type": "string", "minLength": 1},
                        "archive_interval_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                        },
                        "retention_seconds": {"type": "integer", "minimum": 1},
                        "coordination_ttl_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                        },
                        "coordination_wait_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                        },
                        "event_poll_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "max_preview_events": {"type": "integer", "minimum": 1},
                        "preview_retention_seconds": {"type": "integer", "minimum": 1},
                    },
                    "required": ["dsn", "redis_url"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": True,
                    "supports_actor_authorization": True,
                    "supports_session_attachments": True,
                    "cross_process_subscribe": True,
                    "atomic_worker_fence": True,
                    "transactional_outbox": False,
                    "atomic_session_cas": True,
                },
                availability=ExtensionAvailability(
                    available=all(
                        importlib.util.find_spec(name) is not None
                        for name in ("aiomysql", "redis")
                    ),
                    reason=None
                    if all(
                        importlib.util.find_spec(name) is not None
                        for name in ("aiomysql", "redis")
                    )
                    else "optional aiomysql and redis packages are required",
                ),
                built_in=True,
            ),
            factory=lambda context, dependencies: RedisMysqlSessionStore(
                **{key: value for key, value in context.config.items() if key != "dsn"},
                dsn=str(context.config["dsn"]),
            ),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(EphemeralSessionStore),
                version="2.0.0",
                provides=storage_offers,
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema=empty_config_schema(),
                capabilities={"durable": False, "testing": True},
                built_in=True,
            ),
            factory=lambda context, dependencies: EphemeralSessionStore(),
        )
    )

    registry.register(
        service_registration(
            InMemoryDerivedStateStore.plugin_id,
            "derived-state.store",
            lambda context, deps: InMemoryDerivedStateStore(),
        )
    )
