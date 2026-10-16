"""Freeze host-owned Memory identity at admission and reuse it after recovery."""
import hashlib

from sagents.v2.contracts.principals import MemoryIdentity
from sagents.v2.memory.contracts import MemoryScope

MEMORY_IDENTITY_KEY = "sagents.memory_identity"


def bind_memory_identity(command, context, *, parent_command=None):
    inherited = None
    if parent_command is not None:
        if MEMORY_IDENTITY_KEY in parent_command.config.metadata:
            parent = command_memory_scope(parent_command)
            inherited = MemoryIdentity(user_id=parent.principal_id, workspace_id=parent.workspace_id)
        else:
            # Legacy parents have no trustworthy workspace attribution. New
            # child work gets an isolated namespace, never the owner's memory.
            suffix = hashlib.sha256(command.parent_run_id.encode()).hexdigest()
            inherited = MemoryIdentity(user_id=context.actor.principal_id,
                                       workspace_id=f"legacy:{suffix}")
    identity = context.memory_identity or inherited or MemoryIdentity(
        user_id=context.actor.principal_id, workspace_id=command.agent_id,
    )
    if parent_command is not None and command.config.metadata.get("workspace_policy") == "private_child":
        suffix = hashlib.sha256(command.idempotency_key.encode()).hexdigest()
        identity = identity.model_copy(update={"workspace_id": f"private:{suffix}"})
    return command.model_copy(update={"config": command.config.model_copy(update={
        "metadata": {**command.config.metadata, MEMORY_IDENTITY_KEY: {
            **identity.model_dump(), "tenant_id": context.actor.tenant_id,
        }},
    })})


def command_memory_scope(command, context=None):
    raw = command.config.metadata.get(MEMORY_IDENTITY_KEY)
    if raw is not None:
        if context is not None and raw.get("tenant_id") != context.actor.tenant_id:
            raise PermissionError("Memory identity belongs to another host tenant")
        identity = MemoryIdentity.model_validate({
            "user_id": raw.get("user_id"), "workspace_id": raw.get("workspace_id"),
        })
        return MemoryScope(tenant_id=raw.get("tenant_id"), principal_id=identity.user_id,
                           workspace_id=identity.workspace_id, agent_id=command.agent_id)
    # Old records have no trustworthy workspace attribution. Fail closed rather
    # than accidentally attributing an external user's data to the Agent owner.
    raise ValueError("Run has no trusted Memory identity")
