"""The catalog of peers a tenant may delegate to.

Enabling a peer here hands it the tenant's work and, if one is configured,
their credential. These tests cover what that costs to get wrong: a peer
reachable by another tenant, a key echoed back out of the API, or a card that
is read once and then never again.
"""

from __future__ import annotations

import pytest

from app.server_v2.application import catalog
from app.server_v2.core.errors import ServerError
from tests.app.server_v2.conftest import register_and_login

PEER = {"name": "researcher", "url": "https://peer.example.com"}


def auth(client, username: str = "alice") -> dict[str, str]:
    return {"Authorization": f"Bearer {register_and_login(client, username)}"}


@pytest.mark.timeout(30)
def test_a_peer_can_be_added_listed_and_removed(client):
    headers = auth(client)

    created = client.post("/api/a2a-agents", json=PEER, headers=headers)
    listed = client.get("/api/a2a-agents", headers=headers)
    removed = client.delete("/api/a2a-agents/researcher", headers=headers)

    assert created.status_code == 200
    assert created.json()["data"]["url"] == "https://peer.example.com"
    assert [item["name"] for item in listed.json()["data"]] == ["researcher"]
    assert removed.status_code == 200
    assert client.get("/api/a2a-agents", headers=headers).json()["data"] == []


@pytest.mark.timeout(30)
def test_a_peer_with_no_absolute_url_is_refused(client):
    """There is nowhere to fetch a card from, so the row could only fail later."""

    headers = auth(client)

    missing = client.post(
        "/api/a2a-agents", json={"name": "researcher"}, headers=headers
    )
    relative = client.post(
        "/api/a2a-agents",
        json={"name": "researcher", "url": "/a2a"},
        headers=headers,
    )

    assert missing.status_code == 422
    assert relative.status_code == 422
    assert client.get("/api/a2a-agents", headers=headers).json()["data"] == []


@pytest.mark.timeout(30)
def test_a_peer_s_key_is_reported_as_present_and_never_returned(client):
    headers = auth(client)

    created = client.post(
        "/api/a2a-agents", json={**PEER, "api_key": "sk-peer"}, headers=headers
    )

    body = created.json()["data"]
    assert body["has_api_key"] is True
    assert "sk-peer" not in created.text
    assert "sk-peer" not in client.get("/api/a2a-agents", headers=headers).text


@pytest.mark.timeout(30)
def test_editing_a_peer_without_resending_the_key_keeps_it(client):
    """A UI that cannot read the key back cannot echo it on save either."""

    headers = auth(client)
    client.post("/api/a2a-agents", json={**PEER, "api_key": "sk-peer"}, headers=headers)

    updated = client.put(
        "/api/a2a-agents/researcher",
        json={**PEER, "description": "Reads the web."},
        headers=headers,
    )

    assert updated.json()["data"]["has_api_key"] is True
    assert updated.json()["data"]["description"] == "Reads the web."


@pytest.mark.timeout(30)
def test_one_tenant_s_peers_are_invisible_to_another(client):
    mine = auth(client, "alice")
    theirs = auth(client, "bob")
    client.post("/api/a2a-agents", json=PEER, headers=mine)

    listed = client.get("/api/a2a-agents", headers=theirs)
    removed = client.delete("/api/a2a-agents/researcher", headers=theirs)

    assert listed.json()["data"] == []
    assert removed.status_code == 404
    assert [
        item["name"] for item in client.get("/api/a2a-agents", headers=mine).json()["data"]
    ] == ["researcher"]


@pytest.mark.timeout(30)
def test_the_api_is_closed_without_a_token(client):
    assert client.get("/api/a2a-agents").status_code in {401, 403}
    assert client.post("/api/a2a-agents", json=PEER).status_code in {401, 403}


@pytest.mark.timeout(30)
def test_refresh_records_what_the_card_advertises_now(client, monkeypatch):
    """A card read at configuration time is a snapshot, and peers add skills."""

    async def fake_discover(config):
        assert config.name == "researcher"
        return ["a2a_researcher_research", "a2a_researcher_summarise"]

    monkeypatch.setattr(catalog, "discover_a2a_skills", fake_discover)
    headers = auth(client)
    client.post("/api/a2a-agents", json=PEER, headers=headers)

    refreshed = client.post("/api/a2a-agents/researcher/refresh", headers=headers)

    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["skills"] == [
        "a2a_researcher_research",
        "a2a_researcher_summarise",
    ]
    assert client.get("/api/a2a-agents", headers=headers).json()["data"][0][
        "skills"
    ] == ["a2a_researcher_research", "a2a_researcher_summarise"]


@pytest.mark.timeout(30)
def test_refreshing_a_peer_that_is_not_configured_is_a_404(client):
    headers = auth(client)

    response = client.post("/api/a2a-agents/ghost/refresh", headers=headers)

    assert response.status_code == 404


@pytest.mark.timeout(30)
def test_a_peer_that_cannot_be_read_reports_why_and_stays_unchanged(client, monkeypatch):
    """Nothing about the record is wrong; the peer is down. Keep what we had."""

    async def fake_discover(config):
        raise ServerError("validation", "a2a discovery failed: no route to host")

    monkeypatch.setattr(catalog, "discover_a2a_skills", fake_discover)
    headers = auth(client)
    client.post("/api/a2a-agents", json=PEER, headers=headers)

    response = client.post("/api/a2a-agents/researcher/refresh", headers=headers)

    assert response.status_code == 422
    assert "no route to host" in response.json()["message"]
    assert client.get("/api/a2a-agents", headers=headers).json()["data"][0]["skills"] == []


@pytest.mark.timeout(30)
def test_every_edit_drops_the_cached_card(client, service, monkeypatch):
    """The transport is unchanged, so nothing else would notice the edit.

    A plugin caches the card it read once. Without this the tenant has no way
    to make the server look at a peer again after fixing it, and a removed peer
    would keep answering for the rest of the process's life.
    """

    async def fake_discover(config):
        return []

    monkeypatch.setattr(catalog, "discover_a2a_skills", fake_discover)
    forgotten: list[str] = []
    monkeypatch.setattr(
        service.a2a_plugins, "invalidate", lambda user_id: forgotten.append(user_id)
    )
    headers = auth(client)
    client.post("/api/a2a-agents", json=PEER, headers=headers)

    client.put(
        "/api/a2a-agents/researcher",
        json={**PEER, "url": "https://peer2.example.com"},
        headers=headers,
    )
    client.post("/api/a2a-agents/researcher/refresh", headers=headers)
    client.delete("/api/a2a-agents/researcher", headers=headers)

    assert len(forgotten) == 3
    assert len(set(forgotten)) == 1
