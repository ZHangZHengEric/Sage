"""Workspace binding rejects missing admission snapshots with a domain error."""

from types import SimpleNamespace

import pytest

from app.v2.server.identity.context import RequestContexts
from app.v2.server.runtime.workspace_binding import ServerWorkspaceBindingProvider
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.state import SessionStoreCoordinator


async def test_binding_without_accepted_configuration_is_rejected(tmp_path):
    provider = ServerWorkspaceBindingProvider(
        host=None,
        config={"owner": "owner", "agent_id": "agent", "workspace": str(tmp_path)},
        store=SessionStoreCoordinator(),
    )
    request = SimpleNamespace(
        context=RequestContexts("en").for_user("owner"), configuration=None,
    )
    try:
        with pytest.raises(SageV2Error) as caught:
            await provider.acquire(request)
        assert caught.value.info.code == "execution.configuration_incompatible"
    finally:
        await provider.close()
