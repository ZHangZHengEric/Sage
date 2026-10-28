from tests.app.v2.server.conftest import make_test_service
from tests.app.v2.server.test_file_downloads import identity
from app.v2.server.main import create_app
from fastapi.testclient import TestClient

from tests.app.v2.server.im.test_feishu import (
    config,
    event,
    signed,
)


def test_connection_provisioning_webhook_and_ownership(
    tmp_path, feishu_creation_probe, monkeypatch
):
    host = make_test_service(
        tmp_path,
        public_base_url="https://sage.example/sage",
        log_level="warning",
    )
    with TestClient(create_app(host)) as client:
        host.im.pause()
        alice, uid = identity(client, "http-im-owner")
        bob, _ = identity(client, "http-im-other")
        agent = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
        body = {
            "agent_id": agent,
            "name": "Feishu",
            "config": config().request_payload(),
        }
        # The creator is always the authenticated user, even with view-as headers.
        assert (
            client.post(
                "/api/im/connections",
                headers=alice,
                json={**body, "owner_user_id": "someone"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/im/connections",
                headers={**bob, "X-Sage-View-User": uid},
                json=body,
            ).status_code
            == 403
        )
        assert (
            client.post("/api/im/connections", headers=bob, json=body).status_code
            == 404
        )
        legacy = {
            "app_id": "cli_test",
            "tenant_key": "tenant",
            "app_secret_env": "SAGE_IM_FEISHU_OTHER",
            "verification_token_env": "SAGE_IM_FEISHU_OTHER",
            "encrypt_key_env": "SAGE_IM_FEISHU_OTHER",
        }
        assert (
            client.post(
                "/api/im/connections", headers=alice, json={**body, "config": legacy}
            ).status_code
            == 422
        )
        from app.v2.server.im.feishu import FeishuChannel
        from app.v2.server.im.contracts import DeliveryError

        async def invalid_credentials(self):
            raise DeliveryError("failed", "feishu.credentials")

        with monkeypatch.context() as patch:
            patch.setattr(FeishuChannel, "probe", invalid_credentials)
            assert (
                client.post("/api/im/connections", headers=alice, json=body).status_code
                == 422
            )
            assert (
                client.get("/api/im/connections", headers=alice).json()["data"]["items"]
                == []
            )
        # Rejected credentials did not reserve the app/tenant identity.
        response = client.post(
            "/api/im/connections",
            headers=alice,
            json=body,
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["owner_user_id"] == uid
        assert response.json()["data"]["credentials_configured"] is True
        assert response.json()["data"]["config"] == {
            "app_id": "cli_test",
            "tenant_key": "tenant",
        }
        cid = response.json()["data"]["id"]
        stored = client.portal.call(host.im.store.get, cid).config
        assert set(stored) == {"app_id", "tenant_key", "credentials_ciphertext"}
        assert "credentials_ciphertext" not in response.text
        assert response.json()["data"]["webhook_url"] == (
            "https://sage.example/sage/api/im/webhooks/" + cid
        )
        assert '"secret"' not in response.text
        own_page = client.get("/api/im/connections", headers=alice)
        assert '"secret"' not in own_page.text and '"verify"' not in own_page.text
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

        # Filter before pagination, even with many accepted deliveries in front.
        async def seed_deliveries():
            from app.v2.server.im.orm import DeliveryRow

            async with host.database.transaction() as db:
                db.add_all(
                    [
                        DeliveryRow(
                            connection_id=cid,
                            source_key=f"filter-{n}",
                            binding_id="unused",
                            generation=1,
                            auth_epoch=1,
                            chat_id="oc_dm",
                            text="",
                            created_at=0,
                            state=state,
                        )
                        for n, state in enumerate(
                            ["platform_accepted"] * 55 + ["failed", "unknown"]
                        )
                    ]
                )

        client.portal.call(seed_deliveries)
        page = client.get(
            f"/api/im/connections/{cid}/deliveries?unresolved=true&limit=1",
            headers=alice,
        ).json()["data"]
        assert [row["state"] for row in page["items"]] == ["failed"]
        after = page["next_cursor"]
        page = client.get(
            f"/api/im/connections/{cid}/deliveries?unresolved=true&limit=1&after={after}",
            headers=alice,
        ).json()["data"]
        assert [row["state"] for row in page["items"]] == ["unknown"]
        assert page["next_cursor"] is None
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


def test_unavailable_connection_is_visible_and_recoverable_over_http(
    tmp_path, feishu_creation_probe
):
    host = make_test_service(
        tmp_path, public_base_url="https://sage.example", log_level="warning"
    )
    with TestClient(create_app(host)) as client:
        host.im.pause()
        alice, _ = identity(client, "key-http-owner")
        agent = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
        row = client.post(
            "/api/im/connections",
            headers=alice,
            json={
                "agent_id": agent,
                "name": "Recoverable",
                "config": config().request_payload(),
            },
        ).json()["data"]
        cid = row["id"]
        key_file = host.paths.data_root / "secrets" / "im-credentials.key"
        original = key_file.read_bytes()
        key_file.write_bytes(b"corrupt")
        result = client.post(f"/api/im/connections/{cid}/test", headers=alice)
        assert result.status_code == 422
        current = client.get(f"/api/im/connections/{cid}", headers=alice).json()["data"]
        assert not current["enabled"]
        assert current["credentials_error"]
        assert (
            client.get(f"/api/im/connections/{cid}/status", headers=alice).json()[
                "data"
            ]["state"]
            == "unavailable"
        )
        assert (
            client.patch(
                f"/api/im/connections/{cid}",
                headers=alice,
                json={
                    "revision": current["revision"],
                    "enabled": True,
                },
            ).status_code
            == 422
        )
        key_file.write_bytes(original)
        assert (
            client.post(f"/api/im/connections/{cid}/test", headers=alice).status_code
            == 200
        )
        status = client.get(f"/api/im/connections/{cid}/status", headers=alice).json()[
            "data"
        ]
        assert status["state"] == "disabled"
        response = client.patch(
            f"/api/im/connections/{cid}",
            headers=alice,
            json={
                "revision": status["revision"],
                "enabled": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["enabled"]
        assert response.json()["data"]["credentials_error"] == ""
