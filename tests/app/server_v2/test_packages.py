import pytest

from tests.app.server_v2.conftest import register_and_login


def test_package_lifecycle_and_owner_isolation(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    saved = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert saved.status_code == 200, saved.text
    ref = saved.json()["data"]["ref"]
    assert (
        client.get(f"/api/agent-packages/{ref}", headers=headers).json()["data"]
        == bundle
    )
    assert (
        client.post(
            f"/api/agent-packages/{ref}/activate", headers=headers, json={}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/agent-packages/{ref}/activate", headers=headers, json={}
        ).status_code
        == 409
    )
    run = client.post(
        "/api/agent-packages/runs",
        headers=headers,
        json=dict(ref=ref, agent_id="assistant", content="hello", operation="test"),
    )
    assert run.status_code == 200, run.text
    import time

    for _ in range(100):
        status = client.get("/api/agent-packages/runs/test", headers=headers)
        assert status.status_code == 200, status.text
        value = status.json()["data"]
        if value.get("terminal") or value.get("needs_attention"):
            break
        time.sleep(0.02)
    assert value["run"]["state"] == "completed", __import__("json").dumps(
        value, indent=2
    )
    assert (
        client.get("/api/agent-packages/runs", headers=headers).json()["data"][0][
            "operation"
        ]
        == "test"
    )
    other = register_and_login(client, "bob")
    foreign = {"Authorization": f"Bearer {other}"}
    assert client.get(f"/api/agent-packages/{ref}", headers=foreign).status_code == 404
    assert (
        client.get("/api/agent-packages/runs/test", headers=foreign).status_code == 404
    )
    assert client.get("/api/agent-packages", headers=foreign).json()["data"] == []


def test_package_cannot_override_host(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    bundle["manifest"]["runtime"]["capabilities"]["session.store"] = {
        "plugin": "sage.session.filesystem",
        "config": {"root": "/tmp/foreign"},
    }
    response = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert response.status_code == 403, response.text
    assert client.get("/api/agent-packages", headers=headers).json()["data"] == []


def settled(client, headers, operation):
    import time

    for _ in range(100):
        response = client.get(f"/api/agent-packages/runs/{operation}", headers=headers)
        assert response.status_code == 200, response.text
        state = response.json()["data"]
        if state.get("terminal") or state.get("needs_attention"):
            return state
        time.sleep(0.02)
    raise AssertionError(state)


@pytest.mark.parametrize("kind", ["user_input", "approval"])
def test_flow_feedback_and_human_only_approval(client, kind):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    bundle["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "main",
    }
    bundle["manifest"]["flows"] = {
        "main": {
            "version": "1",
            "start": "ask",
            "nodes": [
                {
                    "id": "ask",
                    "type": "interaction",
                    "config": {
                        "interaction_type": kind,
                        "payload": {"prompt": "Choose"},
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "ask", "to": "end"}],
        }
    }
    saved = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert saved.status_code == 200, saved.text
    ref = saved.json()["data"]["ref"]
    response = client.post(
        "/api/agent-packages/runs",
        headers=headers,
        json=dict(ref=ref, agent_id="assistant", operation="question", content="ask"),
    )
    assert response.status_code == 200, response.text
    pending = settled(client, headers, "question")
    assert pending["needs_attention"], pending
    body = dict(
        action="reply",
        interaction_id=pending["interaction"]["interaction_id"],
        decision=pending["interaction"]["allowed_decisions"][0],
        payload={"text": "meters"},
    )
    if kind == "approval":
        response = client.post(
            "/api/agent-packages/runs/question/control", headers=headers, json=body
        )
        assert response.status_code == 422, response.text
        body["action"] = "approve"
    response = client.post(
        "/api/agent-packages/runs/question/control", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    assert settled(client, headers, "question")["terminal"]


def test_authorized_source_plugin_runs_through_server(service):
    from fastapi.testclient import TestClient
    from app.server_v2.app import create_app
    from tests.sagents.v2.test_agent_management_matrix import source_plugin_bundle

    calls = []

    async def authorize(action, bundle, context):
        calls.append(action)
        assert bundle.manifest.plugins[0].id == "test.generated"

    service.package_authorizer = authorize
    with TestClient(create_app(service=service)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        bundle = client.get("/api/agent-packages/template", headers=headers).json()[
            "data"
        ]
        source = source_plugin_bundle().model_dump(mode="json")
        for field in ("plugins", "flows"):
            bundle["manifest"][field] = source["manifest"][field]
        bundle["manifest"]["runtime"]["capabilities"] = source["manifest"]["runtime"][
            "capabilities"
        ]
        bundle["manifest"]["agents"]["assistant"]["entrypoint"] = {
            "type": "flow",
            "flow": "main",
        }
        bundle["files"] = source["files"]
        response = client.post("/api/agent-packages", headers=headers, json=bundle)
        assert response.status_code == 200, response.text
        reference = response.json()["data"]["ref"]
        response = client.post(
            "/api/agent-packages/runs",
            headers=headers,
            json=dict(
                ref=reference,
                agent_id="assistant",
                operation="source",
                content="calculate",
            ),
        )
        assert response.status_code == 200, response.text
        assert (
            settled(client, headers, "source")["flow_results"]["calculate"]["answer"]
            == 42
        )
        assert "load_source_plugin" in calls


@pytest.mark.parametrize(
    "change", ["model", "tools", "budget", "source", "credentials"]
)
def test_package_grants_fail_before_saving(client, change):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    if change == "model":
        next(iter(bundle["manifest"]["models"].values()))["model"] = "foreign-model"
    elif change == "tools":
        bundle["manifest"]["agents"]["assistant"]["tools"] = ["not_granted"]
    elif change == "budget":
        bundle["manifest"]["agents"]["assistant"]["budgets"]["max_steps"] = 10001
    elif change == "credentials":
        bundle["manifest"]["credentials"] = {
            "secret": {"source": "env", "key": "PRIVATE_SECRET"}
        }
    else:
        bundle["manifest"]["plugins"] = [{"id": "test.source", "version": "1"}]
        bundle["files"]["extensions/test.source.py"] = (
            'raise AssertionError("must never load")'
        )
    response = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert response.status_code == 403, response.text
    assert client.get("/api/agent-packages", headers=headers).json()["data"] == []


def test_agent_creates_agent_through_management_tool(service):
    from fastapi.testclient import TestClient
    from app.server_v2.app import create_app
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_agent_management_matrix import tool_step
    from tests.app.server_v2.conftest import scripted_hello

    with TestClient(create_app(service=service)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        child = client.get("/api/agent-packages/template", headers=headers).json()[
            "data"
        ]
        child["manifest"]["metadata"]["id"] = "user.child"
        parent = client.get("/api/agent-packages/template", headers=headers).json()[
            "data"
        ]
        parent["manifest"]["agents"]["assistant"]["tools"] = ["agent_package_save"]
        # Saving and building do not consume scripted responses.
        service._fallback_model = ScriptedModelProvider(
            (
                tool_step("agent_package_save", {"bundle": child}, "create"),
                *scripted_hello()._steps,
            )
        )
        saved = client.post("/api/agent-packages", headers=headers, json=parent)
        assert saved.status_code == 200, saved.text
        response = client.post(
            "/api/agent-packages/runs",
            headers=headers,
            json=dict(
                ref=saved.json()["data"]["ref"],
                agent_id="assistant",
                operation="parent",
                content="Create a child",
            ),
        )
        assert response.status_code == 200, response.text
        state = settled(client, headers, "parent")
        assert state["run"]["state"] == "completed", state
        assert {
            p["package"]
            for p in client.get("/api/agent-packages", headers=headers).json()["data"]
        } == {"user.assistant", "user.child"}


def test_spa_cannot_serve_outside_dist(service, tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient

    module = importlib.import_module("app.server_v2.app")
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("studio")
    (tmp_path / "secret.txt").write_text("private")
    monkeypatch.setattr(module, "WEB_DIST", root)
    with TestClient(module.create_app(service=service)) as client:
        assert client.get("/studio").text == "studio"
        assert client.get("/%2e%2e%2fsecret.txt").status_code == 404
        assert client.get("/api/not-a-route").status_code == 404


@pytest.mark.asyncio
async def test_server_close_retains_failed_resources_for_retry(tmp_path, monkeypatch):
    from tests.app.server_v2.conftest import make_test_service

    service = make_test_service(tmp_path)
    await service.start()
    app, model = service.application, service._host_models
    close = app.close
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("close failed")
        await close()

    monkeypatch.setattr(app, "close", flaky)
    with pytest.raises(RuntimeError, match="close failed"):
        await service.close()
    assert service._application is app and service._host_models is model
    await service.close()
    assert service._application is None and service._host_models is None


@pytest.mark.asyncio
async def test_pending_package_recovers_on_server_restart(tmp_path):
    import asyncio
    from tests.app.server_v2.conftest import make_test_service
    from sagents.v2.agent.management import AgentPackageBundle

    first = make_test_service(tmp_path)
    await first.start()
    user = await first.users.admin()
    context = first.request_context(user.user_id)
    data = await first.agent_management.template(context)
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "main",
    }
    data["manifest"]["flows"] = {
        "main": {
            "version": "1",
            "start": "ask",
            "nodes": [
                {
                    "id": "ask",
                    "type": "interaction",
                    "config": {
                        "interaction_type": "user_input",
                        "payload": {"prompt": "Choose"},
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "ask", "to": "end"}],
        }
    }
    try:
        saved = await first.agent_management.save(
            AgentPackageBundle.model_validate(data), context
        )
        await first.agent_management.run(
            saved["ref"], "assistant", "ask", "restart", context
        )
        async with asyncio.timeout(5):
            while True:
                pending = await first.agent_management.status("restart", context)
                if pending["needs_attention"]:
                    break
                await asyncio.sleep(0.01)
    finally:
        await first.close()
    second = make_test_service(tmp_path)
    second.users, second.catalog = first.users, first.catalog
    await second.start()
    try:
        async with asyncio.timeout(5):
            while second.agent_management.capacity()["applications"] == 0:
                await asyncio.sleep(0.01)
        pending = await second.agent_management.status("restart", context)
        await second.agent_management.control(
            "restart",
            "reply",
            context,
            decision="submit",
            interaction_id=pending["interaction"]["interaction_id"],
            payload={"text": "meters"},
        )
        async with asyncio.timeout(5):
            while not (await second.agent_management.status("restart", context))[
                "terminal"
            ]:
                await asyncio.sleep(0.01)
        assert len(await second.agent_management.list_runs(context)) == 1
    finally:
        await second.close()


def test_flow_executes_member_agent_with_host_limits(client):
    import copy

    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    bundle["manifest"]["agents"]["worker"] = copy.deepcopy(
        bundle["manifest"]["agents"]["assistant"]
    )
    bundle["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "main",
    }
    bundle["manifest"]["flows"] = {
        "main": {
            "version": "1",
            "start": "work",
            "nodes": [
                {"id": "work", "type": "agent", "agent": "worker"},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "work", "to": "end"}],
        }
    }
    response = client.post("/api/agent-packages", headers=headers, json=bundle)
    assert response.status_code == 200, response.text
    ref = response.json()["data"]["ref"]
    response = client.post(
        "/api/agent-packages/runs",
        headers=headers,
        json=dict(
            ref=ref, agent_id="assistant", operation="flow-member", content="hello"
        ),
    )
    assert response.status_code == 200, response.text
    state = settled(client, headers, "flow-member")
    assert state["run"]["state"] == "completed", state
    assert state["flow_results"]["work"]


def test_source_tool_plugin_uses_standard_registration(service):
    from fastapi.testclient import TestClient
    from app.server_v2.app import create_app
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_agent_management_matrix import tool_step
    from tests.app.server_v2.conftest import scripted_hello

    async def authorize(action, bundle, context):
        assert bundle.manifest.plugins[0].id == "test.scale"

    service.package_authorizer = authorize
    provider = ScriptedModelProvider(
        (tool_step("scale", {"value": 4}, "scale"), *scripted_hello()._steps)
    )
    service._fallback_model = provider
    with TestClient(create_app(service=service)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        bundle = client.get("/api/agent-packages/template", headers=headers).json()[
            "data"
        ]
        bundle["manifest"]["plugins"] = [{"id": "test.scale", "version": "1.0.0"}]
        bundle["manifest"]["runtime"]["capabilities"] = {
            "tool.catalog": {"plugin": "test.scale", "name": "generated"}
        }
        bundle["manifest"]["agents"]["assistant"]["tools"] = ["scale"]
        bundle["files"]["extensions/test.scale.py"] = """
from sagents.v2.runtime.extensions import ExtensionRegistration, ExtensionDescriptor, CapabilityOffer, ExtensionScope
from sagents.v2.tool.decorated import DecoratedToolProvider
from sagents.v2.tool.decorators import tool
class Tools:
    @tool(description="Double a number", plan_safe=True)
    async def scale(self, value: int) -> dict:
        return {"result": value * 2}
registration = ExtensionRegistration(
    descriptor=ExtensionDescriptor(plugin_id="test.scale", version="1.0.0", name="Scale",
        provides=(CapabilityOffer(capability="tool.catalog", api_version="2", name="generated"), CapabilityOffer(capability="tool.executor", api_version="2", name="generated")),
        supported_scopes=frozenset({ExtensionScope.AGENT})),
    factory=lambda context, dependencies: DecoratedToolProvider(Tools()),
    start=lambda provider, context, dependencies: {"tool.catalog:generated": provider.catalog, "tool.executor:generated": provider.executor})
"""
        response = client.post("/api/agent-packages", headers=headers, json=bundle)
        assert response.status_code == 200, response.text
        ref = response.json()["data"]["ref"]
        response = client.post(
            "/api/agent-packages/runs",
            headers=headers,
            json=dict(
                ref=ref, agent_id="assistant", operation="scale", content="double 4"
            ),
        )
        assert response.status_code == 200, response.text
        state = settled(client, headers, "scale")
        if state["needs_attention"]:
            question = state["interaction"]
            response = client.post(
                "/api/agent-packages/runs/scale/control",
                headers=headers,
                json=dict(
                    action="approve",
                    interaction_id=question["interaction_id"],
                    decision="approve",
                    payload={},
                ),
            )
            assert response.status_code == 200, response.text
            state = settled(client, headers, "scale")
        assert state["run"]["state"] == "completed", state
        assert any(
            "8" in str(message.content)
            for message in provider.requests[-1].messages
            if message.role == "tool"
        )


def test_events_are_cursor_based_and_owner_scoped(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    bundle = client.get("/api/agent-packages/template", headers=headers).json()["data"]
    saved = client.post("/api/agent-packages", headers=headers, json=bundle).json()[
        "data"
    ]
    client.post(
        "/api/agent-packages/runs",
        headers=headers,
        json=dict(
            ref=saved["ref"], agent_id="assistant", content="hello", operation="events"
        ),
    )
    settled(client, headers, "events")
    first = client.get(
        "/api/agent-packages/runs/events/events?limit=2", headers=headers
    ).json()["data"]
    assert len(first["events"]) == 2 and not first["terminal"]
    rest = client.get(
        f"/api/agent-packages/runs/events/events?after_sequence={first['cursor']}",
        headers=headers,
    ).json()["data"]
    assert rest["terminal"]
    assert all(item["run_sequence"] > first["cursor"] for item in rest["events"])
    foreign = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
    assert (
        client.get(
            "/api/agent-packages/runs/events/events", headers=foreign
        ).status_code
        == 404
    )
    assert (
        client.get("/api/agent-packages/capacity", headers=headers).status_code == 403
    )


def test_a_package_run_can_reach_the_tenant_s_own_a2a_peers(tmp_path):
    """A peer is configured on the tenant, not declared in the package.

    The package's manifest names official tools, which is all a package author
    can name: an A2A peer's Tools only exist once its card has been read. Being
    composed into the Run is therefore not enough — without a grant the model
    sees the Tool and is refused the moment it uses it.
    """

    from fastapi.testclient import TestClient
    from sagents.v2.testing.plugins import ScriptedModelProvider

    from app.server_v2.app import create_app
    from app.server_v2.services.a2a_client import A2APluginCache
    from tests.app.server_v2.conftest import make_test_service
    from tests.app.server_v2.test_a2a_resume import _step
    from tests.sagents.v2.test_a2a_tool_bridge_matrix import FakePeer

    transport = FakePeer()
    provider = ScriptedModelProvider(
        (
            _step(
                1,
                "I will ask the researcher.",
                "a2a_researcher_research",
                {"message": "what is new"},
            ),
            *(_step(index, "researcher says: the answer") for index in range(2, 4)),
        )
    )
    service = make_test_service(tmp_path, model_provider=provider)
    service.a2a_plugins = A2APluginCache(transport=transport)

    with TestClient(create_app(service=service)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        created = client.post(
            "/api/a2a-agents",
            json={"name": "researcher", "url": "https://peer.example.com"},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        bundle = client.get("/api/agent-packages/template", headers=headers).json()[
            "data"
        ]
        saved = client.post("/api/agent-packages", headers=headers, json=bundle).json()[
            "data"
        ]
        started = client.post(
            "/api/agent-packages/runs",
            headers=headers,
            json=dict(
                ref=saved["ref"],
                agent_id="assistant",
                content="what is new",
                operation="delegate",
            ),
        )
        assert started.status_code == 200, started.text

        pending = settled(client, headers, "delegate")
        assert pending["needs_attention"], pending
        approved = client.post(
            "/api/agent-packages/runs/delegate/control",
            headers=headers,
            json=dict(
                action="approve",
                interaction_id=pending["interaction"]["interaction_id"],
                decision="approve_once",
            ),
        )
        assert approved.status_code == 200, approved.text
        assert settled(client, headers, "delegate")["terminal"]

    assert len(transport.sent) == 1
    message = transport.sent[0][1]["params"]["message"]
    assert message["parts"][0]["text"] == "what is new"
