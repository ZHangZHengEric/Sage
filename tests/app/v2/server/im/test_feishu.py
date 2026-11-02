import json

import httpx
import pytest
from lark_oapi.core.http import Transport
from lark_oapi.core.model import RawResponse

from app.v2.server.im.feishu import FeishuChannel, FeishuConfig
from app.v2.server.im.contracts import DeliveryError


def config():
    return FeishuConfig(
        app_id="cli_test", app_secret="secret", web_url="https://sage.example"
    )


def event(text="hello", **message):
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt1",
            "event_type": "im.message.receive_v1",
            "app_id": "cli_test",
            "tenant_key": "tenant",
        },
        "event": {
            "sender": {
                "sender_type": "user",
                "tenant_key": "tenant",
                "sender_id": {"open_id": "ou_owner"},
            },
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_dm",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}),
                **message,
            },
        },
    }


async def admit_event(host, conn, payload):
    message = (await host.im.channel(conn)).normalize(payload)
    if message is not None:
        await host.im.receive(conn.id, message)


@pytest.fixture
async def channel():
    value = FeishuChannel(config())
    yield value
    await value.close()


async def test_normalizes_only_the_bound_apps_private_user_text(channel):
    msg = channel.normalize(event())
    assert (msg.sender_id, msg.chat_id, msg.message_id, msg.text) == (
        "ou_owner",
        "oc_dm",
        "om_1",
        "hello",
    )
    assert channel.normalize(event(chat_type="group")) is None
    assert channel.normalize(event(message_type="image")) is None
    for field in ("app_id", "tenant_key"):
        payload = event()
        payload["header"][field] = "wrong"
        with pytest.raises(ValueError):
            channel.normalize(payload)


@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("timeout", "unknown"),
        ("limit", "retry"),
        ("server", "unknown"),
        ("rejected", "failed"),
        ("invalid", "unknown"),
        ("ok", None),
    ],
)
async def test_official_api_uses_stable_uuid_and_never_retries_send(
    channel, monkeypatch, case, outcome
):
    calls = []

    async def execute(conf, req, option=None):
        raw = RawResponse()
        raw.headers = {}
        raw.status_code = 200
        if "tenant_access_token" in req.uri:
            assert req.body.app_id == "cli_test" and req.body.app_secret == "secret"
            data = {"code": 0, "tenant_access_token": "token", "expire": 7200}
        else:
            calls.append(req)
            assert req.body.uuid == "stable-id" and req.body.receive_id == "oc_dm"
            assert option.tenant_access_token == "token"
            if case == "timeout":
                raise httpx.ReadTimeout("possibly sent")
            data = {"code": 0, "data": {"message_id": "receipt"}}
            if case == "limit":
                raw.status_code, data = 429, {"code": 99991400}
            if case == "server":
                raw.status_code, data = 503, {"code": 1}
            if case == "rejected":
                data = {"code": 9999}
            if case == "invalid":
                data = {"code": 0, "data": {}}
        raw.content = json.dumps(data).encode()
        return raw

    monkeypatch.setattr(Transport, "aexecute", execute)
    if outcome:
        with pytest.raises(DeliveryError) as exc:
            await channel.send("oc_dm", "hello", "stable-id")
        assert exc.value.outcome == outcome
    else:
        assert await channel.send("oc_dm", "hello", "stable-id") == "receipt"
    assert len(calls) == 1
