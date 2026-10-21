"""Workspace binding rejects missing admission snapshots with a domain error."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.v2.server.identity.context import RequestContexts
from app.v2.server.runtime.workspace_binding import ServerWorkspaceBindingProvider
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.session.state import SessionStoreCoordinator


@pytest.mark.parametrize(("configured", "reason"), [
    (False, "Run has no accepted execution configuration"),
    (True, "binding differs from the admitted execution configuration"),
])
async def test_binding_without_matching_accepted_configuration_is_rejected(tmp_path, configured, reason):
    provider = ServerWorkspaceBindingProvider(
        host=None,
        config={"owner": "owner", "agent_id": "agent", "workspace": str(tmp_path)},
        store=SessionStoreCoordinator(),
    )
    provider.access.get_start_command = AsyncMock(return_value=SimpleNamespace(
        config=SimpleNamespace(execution_snapshot=None),
    ))
    request = SimpleNamespace(
        context=RequestContexts("en").for_user("owner"), run_id="run",
        configuration=SimpleNamespace(workspace_root=str(tmp_path)) if configured else None,
    )
    try:
        with pytest.raises(SageV2Error) as caught:
            await provider.acquire(request)
        assert caught.value.info == RuntimeErrorInfo(
            code="execution.configuration_incompatible", category=ErrorCategory.VALIDATION,
            message=reason, message_key="error.execution.configuration_incompatible",
            message_params={"reason": reason}, safe_to_resume=False,
        )
    finally:
        await provider.close()
