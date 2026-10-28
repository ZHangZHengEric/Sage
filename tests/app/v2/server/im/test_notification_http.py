"""Interactive and scheduler callers select only the owner's paired IM route."""

from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.conftest import make_test_service, scripted_hello
from tests.app.v2.server.im.test_feishu import config, event, signed
from tests.app.v2.server.test_file_downloads import identity
from tests.app.v2.server.test_agui_chat import _run_input


def setup_route(host, client):
    owner, uid = identity(client, "notify-http-owner")
    agent = client.get("/api/agents", headers=owner).json()["data"][0]["id"]
    conn = client.post(
        "/api/im/connections",
        headers=owner,
        json={
            "agent_id": agent,
            "name": "My IM",
            "config": config().request_payload(),
        },
    ).json()["data"]
    cid = conn["id"]
    pairing = client.post(f"/api/im/connections/{cid}/pairings", headers=owner).json()[
        "data"
    ]
    raw, headers = signed(event(pairing["command"]))
    assert (
        client.post(f"/api/im/webhooks/{cid}", content=raw, headers=headers).status_code
        == 200
    )
    current = client.portal.call(host.im.store.get, cid)
    channel = client.portal.call(host.im.channel, current)
    sent = []

    async def send(chat, text, uid):
        sent.append((chat, text))
        return "receipt-" + uid

    channel.send = send
    return owner, uid, agent, cid, sent


def test_web_and_scheduled_run_notify_the_owners_im_with_fallback(
    tmp_path, feishu_creation_probe
):
    host = make_test_service(
        tmp_path,
        model_provider=scripted_hello(2),
        public_base_url="https://sage.example",
        log_level="warning",
    )
    with TestClient(create_app(host)) as client:
        host.im.pause()
        owner, uid, agent, cid, sent = setup_route(host, client)
        body = {
            **_run_input("web-notification", "web-request"),
            "notification_connection_id": cid,
        }
        response = client.post("/api/agent", headers=owner, json=body)
        assert response.status_code == 200, response.text
        for _ in range(3):
            client.portal.call(host.im.tick)
        assert sent.count(("oc_dm", "hello")) == 1
        issued = client.post(
            "/api/keys",
            headers=owner,
            json={
                "agent_id": agent,
                "name": "scheduler",
                "scopes": ["a2a:invoke", "a2a:read"],
            },
        ).json()["data"]
        scheduled = client.post(
            f"/api/agents/{agent}/runs",
            headers={
                "Authorization": "Bearer " + issued["api_key"],
                "SAGE-TENANT-ID": uid,
            },
            json={
                **_run_input("scheduled-notification", "scheduled-request"),
                "notification_connection_id": cid,
            },
        )
        assert scheduled.status_code == 200, scheduled.text
        for _ in range(3):
            client.portal.call(host.im.tick)
        assert sent.count(("oc_dm", "hello")) == 2
        scheduled_replay = client.post(
            f"/api/agents/{agent}/runs",
            headers={
                "Authorization": "Bearer " + issued["api_key"],
                "SAGE-TENANT-ID": uid,
            },
            json={
                **_run_input("scheduled-notification", "scheduled-request"),
                "notification_connection_id": cid,
            },
        )
        assert scheduled_replay.status_code == 200, scheduled_replay.text
        # HTTP replay never schedules a second completion notification.
        replay = client.post("/api/agent", headers=owner, json=body)
        assert replay.status_code == 200, replay.text
        client.portal.call(host.im.tick)
        assert sent.count(("oc_dm", "hello")) == 2


def test_notification_target_cannot_be_injected_from_another_owner_or_business_tenant(
    tmp_path, feishu_creation_probe
):
    host = make_test_service(
        tmp_path, public_base_url="https://sage.example", log_level="warning"
    )
    with TestClient(create_app(host)) as client:
        host.im.pause()
        owner, uid, agent, cid, _ = setup_route(host, client)
        other, _ = identity(client, "notify-foreign")
        response = client.post(
            "/api/agent",
            headers=other,
            json={**_run_input(), "notification_connection_id": cid},
        )
        assert response.status_code == 404, response.text
        issued = client.post(
            "/api/keys",
            headers=owner,
            json={
                "agent_id": agent,
                "name": "scheduler",
                "scopes": ["a2a:invoke", "a2a:read"],
            },
        ).json()["data"]
        response = client.post(
            f"/api/agents/{agent}/runs",
            headers={
                "Authorization": "Bearer " + issued["api_key"],
                "SAGE-TENANT-ID": "another-business-tenant",
            },
            json={**_run_input(), "notification_connection_id": cid},
        )
        assert response.status_code == 403, response.text
        assert client.portal.call(host.threads.list_for, uid) == []


def test_scheduler_key_revocation_suppresses_pending_notification(
    tmp_path, feishu_creation_probe
):
    host = make_test_service(
        tmp_path, public_base_url="https://sage.example", log_level="warning"
    )
    with TestClient(create_app(host)) as client:
        host.im.pause()
        owner, uid, agent, cid, sent = setup_route(host, client)
        issued = client.post(
            "/api/keys",
            headers=owner,
            json={
                "agent_id": agent,
                "name": "scheduler",
                "scopes": ["a2a:invoke", "a2a:read"],
            },
        ).json()["data"]
        response = client.post(
            f"/api/agents/{agent}/runs",
            headers={
                "Authorization": "Bearer " + issued["api_key"],
                "SAGE-TENANT-ID": uid,
            },
            json={**_run_input(), "notification_connection_id": cid},
        )
        assert response.status_code == 200, response.text
        assert (
            client.delete("/api/keys/" + issued["key_id"], headers=owner).status_code
            == 200
        )
        for _ in range(3):
            client.portal.call(host.im.tick)
        assert ("oc_dm", "hello") not in sent
