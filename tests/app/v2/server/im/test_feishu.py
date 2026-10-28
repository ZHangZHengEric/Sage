import base64
import hashlib
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.v2.server.im.feishu import FeishuChannel, FeishuConfig
from app.v2.server.im.contracts import DeliveryError

def config():
    return FeishuConfig(
        app_id="cli_test",
        tenant_key="tenant",
        app_secret="secret",
        verification_token="verify",
        encrypt_key="key",
    )


def event(text="hello", **message):
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt1",
            "event_type": "im.message.receive_v1",
            "app_id": "cli_test",
            "tenant_key": "tenant",
            "token": "verify",
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


def signed(payload, *, encrypted=True, timestamp=None):
    raw = json.dumps(payload).encode()
    if encrypted:
        pad = padding.PKCS7(128).padder()
        padded = pad.update(raw) + pad.finalize()
        iv = b"0123456789abcdef"
        enc = Cipher(
            algorithms.AES(hashlib.sha256(b"key").digest()), modes.CBC(iv)
        ).encryptor()
        raw = json.dumps(
            {
                "encrypt": base64.b64encode(
                    iv + enc.update(padded) + enc.finalize()
                ).decode()
            }
        ).encode()
    stamp = str(timestamp or int(time.time()))
    headers = {
        "x-lark-request-timestamp": stamp,
        "x-lark-request-nonce": "nonce",
        "x-lark-signature": hashlib.sha256(
            (stamp + "nonce" + "key").encode() + raw
        ).hexdigest(),
    }
    return raw, headers


@pytest.fixture
def channel():
    return FeishuChannel(config())


def test_decrypt_and_normalize_private_text(channel):
    raw, headers = signed(event())
    msg = channel.decode(raw, headers)
    assert (msg.sender_id, msg.chat_id, msg.message_id, msg.text) == (
        "ou_owner",
        "oc_dm",
        "om_1",
        "hello",
    )


def test_challenge_accepts_token_without_signature(channel):
    assert channel.decode(
        json.dumps(
            {"type": "url_verification", "token": "verify", "challenge": "123"}
        ).encode(),
        {},
    ) == {"challenge": "123"}


@pytest.mark.parametrize("change", ["signature", "timestamp", "tenant", "token", "app"])
def test_rejects_forgery_and_replay(channel, change):
    payload = event()
    if change in ("tenant", "token", "app"):
        payload["header"][
            {"tenant": "tenant_key", "token": "token", "app": "app_id"}[change]
        ] = "wrong"
    raw, headers = signed(payload, timestamp=1 if change == "timestamp" else None)
    if change == "signature":
        headers["x-lark-signature"] = "bad"
    with pytest.raises(ValueError):
        channel.decode(raw, headers)


def test_ignores_groups_and_non_text(channel):
    assert channel.decode(*signed(event(chat_type="group"))) is None
    assert channel.decode(*signed(event(message_type="image"))) is None


async def test_transport_reports_rate_limit_and_unknown_without_duplicate_retry(
    channel,
):
    calls = []

    async def handler(request):
        calls.append(request)
        if "tenant_access_token" in request.url.path:
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        raise httpx.ReadTimeout("possibly sent")

    channel.client = httpx.AsyncClient(
        base_url="https://open.feishu.cn", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(DeliveryError) as exc:
            await channel.send("oc_dm", "hello", "stable-id")
        assert exc.value.outcome == "unknown"
        assert len(calls) == 2
        assert json.loads(calls[-1].content)["uuid"] == "stable-id"
    finally:
        await channel.close()


@pytest.mark.parametrize("payload", [[], {"header": []}, {"header": {}, "event": []}])
def test_malformed_platform_objects_fail_closed(channel, payload):
    with pytest.raises(ValueError):
        channel.decode(*signed(payload))


@pytest.mark.parametrize("malformed", [{"code": 0, "data": {}}, []])
async def test_rate_limit_is_retryable_but_platform_acceptance_requires_receipt(
    channel,
    malformed,
):
    await channel.client.aclose()
    mode = ["limited"]

    async def handler(request):
        if "tenant_access_token" in request.url.path:
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        if mode[0] == "limited":
            return httpx.Response(
                429, headers={"Retry-After": "7"}, json={"code": 99991400}
            )
        if mode[0] == "malformed":
            return httpx.Response(200, json=malformed)
        return httpx.Response(
            200, json={"code": 0, "data": {"message_id": "om_receipt"}}
        )

    channel.client = httpx.AsyncClient(
        base_url="https://open.feishu.cn", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(DeliveryError) as exc:
            await channel.send("oc_dm", "hello", "stable-id")
        assert (exc.value.outcome, exc.value.retry_after) == ("retry", 7)
        mode[0] = "malformed"
        with pytest.raises(DeliveryError) as exc:
            await channel.send("oc_dm", "hello", "stable-id")
        assert exc.value.outcome == "unknown"
        mode[0] = "accepted"
        assert await channel.send("oc_dm", "hello", "stable-id") == "om_receipt"
    finally:
        await channel.close()
