"""Official process-local and distributed Job runtime registrations."""

from __future__ import annotations

import importlib.util

from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.extensions.contracts import (
    ExtensionAvailability,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import (
    implementation_identity,
    register_plugin,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_job_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        InMemoryJobRuntime,
        "execution.job-runtime",
        lambda context, dependencies: InMemoryJobRuntime(
            context.config.get("runners", {}),
            max_concurrent_jobs=int(context.config.get("max_concurrent_jobs", 32)),
            max_admitted_jobs=int(context.config.get("max_admitted_jobs", 1024)),
            max_job_output_bytes=int(
                context.config.get("max_job_output_bytes", 8 * 1024 * 1024)
            ),
            max_job_output_chunks=int(
                context.config.get("max_job_output_chunks", 8192)
            ),
            max_buffered_output_bytes=int(
                context.config.get("max_buffered_output_bytes", 256 * 1024 * 1024)
            ),
            max_buffered_output_chunks=int(
                context.config.get("max_buffered_output_chunks", 65536)
            ),
            terminal_ttl_seconds=int(
                context.config.get("terminal_ttl_seconds", 86_400)
            ),
            max_retained_terminal_jobs=int(
                context.config.get("max_retained_terminal_jobs", 4096)
            ),
            max_retained_output_bytes=int(
                context.config.get("max_retained_output_bytes", 256 * 1024 * 1024)
            ),
            output_reconnect_window_seconds=int(
                context.config.get("output_reconnect_window_seconds", 300)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "properties": {
                "runners": {"type": "object"},
                "max_concurrent_jobs": {"type": "integer", "minimum": 1},
                "max_admitted_jobs": {"type": "integer", "minimum": 1},
                "max_job_output_bytes": {"type": "integer", "minimum": 1},
                "max_job_output_chunks": {"type": "integer", "minimum": 1},
                "max_buffered_output_bytes": {"type": "integer", "minimum": 1},
                "max_buffered_output_chunks": {"type": "integer", "minimum": 1},
                "terminal_ttl_seconds": {"type": "integer", "minimum": 1},
                "max_retained_terminal_jobs": {"type": "integer", "minimum": 0},
                "max_retained_output_bytes": {"type": "integer", "minimum": 0},
                "output_reconnect_window_seconds": {
                    "type": "integer",
                    "minimum": 0,
                },
            },
            "additionalProperties": False,
        },
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )

    from copy import deepcopy

    from sagents.v2.runtime.execution.jobs import RedisDistributedJobRuntime

    original = registry.get(InMemoryJobRuntime.plugin_id).descriptor

    schema = deepcopy(original.config_schema)

    schema["properties"].update(
        {
            "redis_url": {"type": "string", "minLength": 1},
            "key_prefix": {"type": "string", "minLength": 1},
            "lease_seconds": {"type": "number", "exclusiveMinimum": 0},
            "poll_interval_seconds": {"type": "number", "exclusiveMinimum": 0},
        }
    )

    schema["required"] = ["redis_url"]

    registry.register(
        ExtensionRegistration(
            descriptor=original.model_copy(
                update={
                    **implementation_identity(RedisDistributedJobRuntime),
                    "availability": ExtensionAvailability(
                        available=importlib.util.find_spec("redis") is not None,
                        reason=None
                        if importlib.util.find_spec("redis") is not None
                        else "optional redis package is required",
                    ),
                    "config_schema": schema,
                    "capabilities": {
                        **original.capabilities,
                        "durable_across_process_restart": True,
                        "multi_process_writes": True,
                        "supports_reconnect": True,
                        "supports_remote_cancel": True,
                        "supports_adoption": False,
                    },
                }
            ),
            factory=lambda context, dependencies: RedisDistributedJobRuntime(
                **context.config
            ),
        )
    )
