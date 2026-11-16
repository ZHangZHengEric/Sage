import asyncio

from ag_ui.core import RunAgentInput, UserMessage
from httpx import ASGITransport, AsyncClient

from app.v2.server.config.plugins import ServerPluginConfig, revision
from app.v2.server.main import create_app
from sagents.v2.contracts.run_state import RunState
from tests.app.v2.server.conftest import make_test_service, scripted_hello


class GatedModel:
    def __init__(self):
        self.started = asyncio.Queue()
        self.release = {session_id: asyncio.Event() for session_id in ("one", "two", "three", "four")}
        self.provider = scripted_hello(4)

    async def capabilities(self, binding):
        return await self.provider.capabilities(binding)

    async def stream(self, request):
        command = await self.store.get_start_command(request.run_id)
        self.started.put_nowait(command.session_id)
        await self.release[command.session_id].wait()
        async for event in self.provider.stream(request):
            yield event


async def test_admin_hot_updates_global_and_per_user_concurrency(tmp_path):
    model = GatedModel()
    ServerPluginConfig(tmp_path).save({
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
    }, revision({}))
    host = make_test_service(tmp_path, model_provider=model,
                             log_level="warning",
                             max_concurrent_runs=1, max_concurrent_runs_per_user=1)
    await host.start()
    try:
        model.store = host.application.service("session.store")
        service = host.conversations
        first = await host.identity.register("first-user", "secret1")
        other = await host.identity.register("other-user", "secret1")
        path = "/api/admin/runtime/concurrency"
        async with AsyncClient(transport=ASGITransport(app=create_app(host)),
                               base_url="http://testserver") as client:
            async def login(username, password):
                response = await client.post("/api/auth/login", json={
                    "username": username, "password": password,
                })
                assert response.status_code == 200, response.text
                client.cookies.clear()
                return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}

            user_headers = await login("first-user", "secret1")
            admin_headers = await login("admin", "admin12345")
            assert (await client.put(path, headers=user_headers, json={
                "max_concurrent_runs": 2, "max_concurrent_runs_per_user": 2,
            })).status_code == 403
            assert (await client.put(path, headers=admin_headers, json={
                "max_concurrent_runs": 0, "max_concurrent_runs_per_user": 2,
            })).status_code == 422

            async def update(total, per_user):
                limits = {"max_concurrent_runs": total, "max_concurrent_runs_per_user": per_user}
                response = await client.put(path, headers=admin_headers, json=limits)
                assert response.status_code == 200, response.text
                expected = {**limits, "hot_reload_supported": True}
                assert response.json()["data"] == expected
                status = await client.get(path, headers=admin_headers)
                assert status.status_code == 200
                assert status.json()["data"] == expected
                assert host.execution.model_budget.limit == total

            async def start(user, session_id):
                stream = await service.start(
                    RunAgentInput(
                        thread_id=session_id, run_id=session_id, state={}, tools=[], context=[],
                        messages=[UserMessage(id="input", role="user", content="hello")],
                        forwarded_props={},
                    ),
                    user_id=user.user_id,
                )
                await stream.aclose()

            async def state(user, session_id):
                result = await service.result(user_id=user.user_id, session_id=session_id)
                return result["state"]

            async def wait_for_state(user, session_id, expected):
                while (current := await state(user, session_id)) != expected:
                    assert current not in {RunState.FAILED, RunState.CANCELLED, RunState.SUSPENDED}
                    await asyncio.sleep(0.01)

            async with asyncio.timeout(10):
                await start(first, "one")
                assert await model.started.get() == "one"
                await start(first, "two")
                await start(first, "three")
                await start(other, "four")
                assert await state(first, "two") == await state(other, "four") == RunState.QUEUED

                await update(2, 1)
                assert await model.started.get() == "four"
                assert await state(first, "two") == RunState.QUEUED

                await update(3, 2)
                assert await model.started.get() == "two"
                await update(1, 1)
                for session_id, user in (("four", other), ("one", first)):
                    model.release[session_id].set()
                    await wait_for_state(user, session_id, RunState.COMPLETED)
                    assert await state(first, "three") == RunState.QUEUED
                assert await state(first, "two") == RunState.RUNNING
                model.release["two"].set()
                assert await model.started.get() == "three"
                model.release["three"].set()
                await wait_for_state(first, "three", RunState.COMPLETED)
                await wait_for_state(first, "two", RunState.COMPLETED)
    finally:
        await host.close()
