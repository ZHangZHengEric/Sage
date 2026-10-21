"""Official process-local, filesystem and distributed scheduler registrations."""

from __future__ import annotations

import importlib.util

from sagents.v2.runtime.execution.dispatcher import DEFAULT_LEASE_SECONDS
from sagents.v2.runtime.execution.scheduler import (
    FilesystemScheduler,
    InMemoryScheduler,
)
from sagents.v2.runtime.extensions.contracts import (
    ExtensionAvailability,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import register_plugin
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_scheduler_plugins(registry: ExtensionRegistry) -> None:
    register_plugin(
        registry,
        InMemoryScheduler,
        "execution.scheduler",
        lambda context, dependencies: InMemoryScheduler(
            max_pending_items=int(context.config.get("max_pending_items", 1024)),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 4096)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema=_scheduler_config_schema(durable=False),
        capabilities={
            "durable_across_process_restart": False,
            "multi_process_writes": False,
            "supports_leases": True,
            "supports_fencing": True,
            "supports_distributed_claims": False,
            "supports_atomic_tenant_quota": True,
            "supports_atomic_fenced_mutations": True,
        },
    )

    register_plugin(
        registry,
        FilesystemScheduler,
        "execution.scheduler",
        lambda context, dependencies: FilesystemScheduler(
            context.config["root"],
            max_pending_items=int(context.config.get("max_pending_items", 1024)),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 4096)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema=_scheduler_config_schema(durable=True),
        capabilities={
            "durable_across_process_restart": True,
            "multi_process_writes": False,
            "supports_leases": True,
            "supports_fencing": True,
            "supports_distributed_claims": False,
            "supports_atomic_tenant_quota": True,
            "supports_atomic_fenced_mutations": True,
        },
    )

    from sagents.v2.runtime.execution.scheduler import RedisDistributedScheduler

    scheduler_schema = _scheduler_config_schema(durable=False)

    scheduler_schema["properties"].update(
        {
            "redis_url": {"type": "string", "minLength": 1},
            "key_prefix": {"type": "string", "minLength": 1},
            "queue_id": {"type": "string", "minLength": 1},
            "coordination_ttl_seconds": {"type": "number", "exclusiveMinimum": 0},
            "poll_seconds": {"type": "number", "exclusiveMinimum": 0},
        }
    )

    scheduler_schema["properties"]["lease_seconds"]["default"] = 30

    scheduler_schema["required"] = ["redis_url"]

    register_plugin(
        registry,
        RedisDistributedScheduler,
        "execution.scheduler",
        lambda context, dependencies: RedisDistributedScheduler(
            **{
                key: value
                for key, value in context.config.items()
                if key not in {"lease_seconds", "preserve_runs_on_shutdown"}
            }
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema=scheduler_schema,
        availability=ExtensionAvailability(
            available=importlib.util.find_spec("redis") is not None,
            reason=None
            if importlib.util.find_spec("redis") is not None
            else "optional redis package is required",
        ),
        capabilities={
            "durable_across_process_restart": True,
            "multi_process_writes": True,
            "supports_distributed_claims": True,
            "supports_leases": True,
            "supports_fencing": True,
            "supports_atomic_tenant_quota": True,
            "supports_atomic_fenced_mutations": True,
        },
    )


def _scheduler_config_schema(*, durable: bool) -> dict:
    properties = {
        "preserve_runs_on_shutdown": {"type": "boolean", "default": True},
        "max_pending_items": {"type": "integer", "minimum": 1},
        "max_retained_terminal_items": {"type": "integer", "minimum": 0},
        "max_concurrent_runs": {"type": "integer", "minimum": 1},
        "max_concurrent_runs_per_tenant": {"type": "integer", "minimum": 1},
        "lease_seconds": {
            "type": "number",
            "exclusiveMinimum": 0,
            "default": DEFAULT_LEASE_SECONDS,
        },
    }
    required = []
    if durable:
        properties["root"] = {"type": "string", "minLength": 1}
        required.append("root")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
