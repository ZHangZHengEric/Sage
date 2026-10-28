from tests.app.v2.server.conftest import make_test_service
from tests.app.v2.server.test_file_downloads import identity
from app.v2.server.main import create_app
from fastapi.testclient import TestClient

from tests.app.v2.server.im.test_feishu import config, event, signed


def test_connection_provisioning_webhook_and_ownership(tmp_path, monkeypatch):
    for suffix, value in [("SECRET", "secret"), ("TOKEN", "verify"), ("KEY", "key")]:
        monkeypatch.setenv("SAGE_IM_FEISHU_" + suffix, value)
    host = make_test_service(
        tmp_path, public_base_url="https://sage.example", log_level="warning"
    )
    with TestClient(create_app(host)) as client:
        host.im.pause()
        alice, uid = identity(client, "http-im-owner")
        bob, _ = identity(client, "http-im-other")
        agent = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
        admin = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"}
        ).json()["data"]["access_token"]
        body = {
            "owner_user_id": uid,
            "agent_id": agent,
            "name": "Feishu",
            "config": config().model_dump(),
        }
        assert (
            client.post("/api/im/connections", headers=alice, json=body).status_code
            == 403
        )
        response = client.post(
            "/api/im/connections",
            headers={"Authorization": "Bearer " + admin},
            json=body,
        )
        assert response.status_code == 200, response.text
        cid = response.json()["data"]["id"]
        assert '"secret"' not in response.text
        client.cookies.clear()
        assert client.get("/api/im/connections").status_code == 401
        assert (
            client.get("/api/im/connections", headers=bob).json()["data"]["items"] == []
        )
        assert (
            client.post(f"/api/im/connections/{cid}/pairings", headers=bob).status_code
            == 404
        )
        challenge = client.post(
            f"/api/im/connections/{cid}/pairings", headers=alice
        ).json()["data"]
        payload = event("/pair " + challenge["code"])
        raw, headers = signed(payload)
        assert (
            client.post(
                f"/api/im/webhooks/{cid}", content=raw, headers=headers
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/im/connections/{cid}", headers=alice).json()["data"][
                "paired"
            ]
            is True
        )
        assert (
            client.patch(
                f"/api/im/connections/{cid}",
                headers=alice,
                json={"revision": 2, "enabled": False},
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/api/im/connections/{cid}",
                headers=alice,
                json={"revision": 1, "enabled": False},
            ).status_code
            == 200
        )
        raw, headers = signed(event())
        headers["x-lark-signature"] = "fake"
        assert (
            client.post(
                f"/api/im/webhooks/{cid}", content=raw, headers=headers
            ).status_code
            == 401
        )
        assert (
            client.post(f"/api/im/webhooks/{cid}", content=b"x" * 65537).status_code
            == 413
        )

        assert (
            client.delete(
                f"/api/im/connections/{cid}?revision=2", headers=bob
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/im/connections/{cid}?revision=1", headers=alice
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/im/connections/{cid}?revision=2", headers=alice
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/im/connections/{cid}", headers=alice).status_code == 404
        )
