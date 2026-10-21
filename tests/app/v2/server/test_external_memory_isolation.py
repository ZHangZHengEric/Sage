"""WishSeen accounts share an Agent, never its long-term Memory namespace."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal

import pytest

from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from sagents.v2.model import ModelEventKind, ModelResponse, ModelStreamEvent
from tests.app.v2.server.conftest import CompletingJudgeModel
from sagents.v2.memory import MemoryQuery, MemoryService
from sagents.v2.memory.identity import command_memory_scope
from tests.app.v2.server.test_external_chat import make_host, setup_agent


class MemoryTestModel(CompletingJudgeModel):
    async def stream(self, request):
        if request.metadata.get("purpose") == "memory_recall_query":
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED,
                response=ModelResponse(response_id="memory-query",
                    text='{"query":"cobaltcoffee"}', finish_reason="stop"))
            return
        async for event in super().stream(request):
            yield event



@pytest.mark.timeout(30)
def test_wishseen_accounts_have_separate_durable_memory(tmp_path):
    host = make_host(tmp_path, steps=20)
    host.execution.fallback_model = MemoryTestModel(host.execution.fallback_model)
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        configured = client.put(f"/api/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "WishSeen memory acceptance", "tools": ["search_memory"]})
        assert configured.status_code == 200, configured.text
        missing_user = client.post(f"/api/agents/{agent_id}/runs", json={
            "threadId": "no-user", "runId": "create", "messages": [],
        })
        assert missing_user.status_code == 422
        for account, thread, content in (
            ("wishseen-alice", "alice-project-one", "Remember cobaltcoffee preference"),
            ("wishseen-bob", "bob-project-one", "Remember ambertea preference"),
            ("wishseen-alice", "alice-project-two", "hello again"),
        ):
            response = client.post(
                f"/api/agents/{agent_id}/runs", headers={"SAGE-TENANT-ID": account},
                params={"workspace_path": f"projects/{thread}"},
                json={"threadId": thread, "runId": "create",
                      "messages": [{"id": "input", "role": "user", "content": content}]},
            )
            assert response.status_code == 200, response.text
            assert 'RUN_FINISHED' in response.text, response.text

        async def inspect():
            store = host.application.entrypoint().runtime.session_store
            provider = host.application.service("memory.provider")
            scopes = []
            for thread in ("alice-project-one", "bob-project-one", "alice-project-two"):
                run_id = (await store.list_session_runs(thread))[0].run_id
                command = await store.get_start_command(run_id)
                assert command.config.metadata["server_v2.execution"]["key_id"] == client.headers["Authorization"].split(".")[1]
                scopes.append(command_memory_scope(command))
            assert scopes[0] == scopes[2]
            assert scopes[0] != scopes[1]
            assert scopes[0].principal_id == "wishseen-alice"
            assert scopes[1].principal_id == "wishseen-bob"
            assert scopes[0].workspace_id == agent_id
            # Query the same SDK provider the actual successful Runs wrote into.
            import asyncio
            for _ in range(100):
                alice = await provider.recall(MemoryQuery(scope=scopes[2], text="cobaltcoffee"))
                if alice:
                    break
                await asyncio.sleep(0.02)
            bob = await provider.recall(MemoryQuery(scope=scopes[1], text="cobaltcoffee"))
            assert alice, "successful run must automatically persist user memory"
            assert not bob
            return scopes, alice[0].record.memory_id

        scopes, memory_id = cast('BlockingPortal', client.portal).call(inspect)

    # Reopen storage and verify isolation survives a Server restart.
    with TestClient(create_app(make_host(tmp_path))) as restarted:
        async def verify():
            provider = getattr(restarted.app, 'state').service.application.service("memory.provider")
            service = MemoryService(provider)
            assert await provider.get(memory_id, scope=scopes[1]) is None
            assert not (await service.forget(memory_id, scope=scopes[1])).deleted
            assert await provider.get(memory_id, scope=scopes[0]) is not None
            assert (await service.forget(memory_id, scope=scopes[0])).deleted
        cast('BlockingPortal', restarted.portal).call(verify)
