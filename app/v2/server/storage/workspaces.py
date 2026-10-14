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
