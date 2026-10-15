"""Trusted workspace identity shared by execution and file browsing."""
from __future__ import annotations

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

WORKSPACE_USER_KEY = "server_v2.workspace_user_id"


def workspace_user(command, owner_id: str) -> str:
    user_id = command.config.metadata.get(WORKSPACE_USER_KEY)
    if isinstance(user_id, str) and user_id:
        return user_id
    if (command.session_id or "").startswith("external_"):
        # Historical external Sessions stored only hashes. The original user
        # cannot be recovered from those hashes without an explicit mapping.
        raise SageV2Error(RuntimeErrorInfo(
            code="server.workspace.identity_missing", category=ErrorCategory.VALIDATION,
            message="legacy external Session requires a user workspace mapping",
        ))
    return owner_id


async def with_workspace_binding(command, owner_id: str, threads):
    """Resolve old hash-only workspace identity from a verified durable claim."""
    if command.config.metadata.get(WORKSPACE_USER_KEY) or threads is None:
        return command
    binding = await threads.binding(command.session_id)
    if binding is None:
        return command
    if binding.owner_id != owner_id or binding.agent_id != command.agent_id:
        raise SageV2Error(RuntimeErrorInfo(
            code="server.workspace.binding_mismatch", category=ErrorCategory.AUTHORIZATION,
            message="Session workspace binding does not match the Run",
            metadata={"side_effect_state": "not_applied"},
        ))
    return command.model_copy(update={"config": command.config.model_copy(update={
        "metadata": {**command.config.metadata, WORKSPACE_USER_KEY: binding.tenant_id},
    })})
