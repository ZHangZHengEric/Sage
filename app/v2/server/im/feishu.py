"""Feishu self-built app Webhook/text transport; no Agent execution here.

Protocol references and required scopes are documented in im/README.md.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import BaseModel, ConfigDict, Field

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from .contracts import DeliveryError, PrivateMessage


class FeishuConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    app_id: str = Field(pattern=r"^cli_[A-Za-z0-9_]+$", max_length=128)
    tenant_key: str = Field(min_length=1, max_length=128)
    app_secret_env: str = Field(pattern=r"^SAGE_IM_FEISHU_[A-Z0-9_]+$", max_length=128)
    verification_token_env: str = Field(
        pattern=r"^SAGE_IM_FEISHU_[A-Z0-9_]+$", max_length=128
    )
    encrypt_key_env: str = Field(pattern=r"^SAGE_IM_FEISHU_[A-Z0-9_]+$", max_length=128)


def secret(name):
    value = os.environ.get(name, "")
    if not value:
        raise ValueError("IM credential is not configured")
    return value


class FeishuChannel:
    def __init__(self, config: FeishuConfig):
        self.config = config
        self.client = httpx.AsyncClient(
            base_url="https://open.feishu.cn", timeout=15, follow_redirects=False
        )
        self._token = ""
        self._token_until = 0
        self._token_lock = asyncio.Lock()

    def decode(self, body, headers):
        if len(body) > 65536:
            raise ValueError("event too large")
        try:
            key = secret(self.config.encrypt_key_env)
            token = secret(self.config.verification_token_env)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("invalid event")
            if "encrypt" in payload:
                data = base64.b64decode(payload["encrypt"], validate=True)
                if len(data) < 32 or len(data) % 16:
                    raise ValueError("invalid encrypted event")
                decrypt = Cipher(
                    algorithms.AES(hashlib.sha256(key.encode()).digest()),
                    modes.CBC(data[:16]),
                ).decryptor()
                padded = decrypt.update(data[16:]) + decrypt.finalize()
                unpad = padding.PKCS7(128).unpadder()
                payload = json.loads(unpad.update(padded) + unpad.finalize())
            if not isinstance(payload, dict):
                raise ValueError("invalid event")
            header = payload.get("header", {})
            if not isinstance(header, dict):
                raise ValueError("invalid event header")
            supplied_token = payload.get("token", header.get("token"))
            # Feishu omits the token in some encrypted v2 events. Those events
            # are still authenticated by the mandatory signature below.
            if supplied_token is not None and not hmac.compare_digest(
                str(supplied_token), token
            ):
                raise ValueError("invalid event credentials")
            if payload.get("type") == "url_verification":
                if (
                    not isinstance(payload.get("challenge"), str)
                    or supplied_token != token
                ):
                    raise ValueError("invalid challenge")
                return {"challenge": payload["challenge"]}
            stamp = headers.get("x-lark-request-timestamp", "")
            nonce = headers.get("x-lark-request-nonce", "")
            signature = headers.get("x-lark-signature", "")
            expected = hashlib.sha256((stamp + nonce + key).encode() + body).hexdigest()
            if (
                not nonce
                or abs(time.time() - int(stamp)) > 300
                or not hmac.compare_digest(expected, signature)
            ):
                raise ValueError("invalid event signature")
            if (
                header.get("app_id") != self.config.app_id
                or header.get("tenant_key") != self.config.tenant_key
            ):
                raise ValueError("event belongs to another app or tenant")
            if header.get("event_type") != "im.message.receive_v1":
                return None
            event = payload["event"]
            sender, msg = event["sender"], event["message"]
            if (
                sender.get("tenant_key") != self.config.tenant_key
                or sender.get("sender_type") != "user"
            ):
                return None
            if msg.get("chat_type") != "p2p" or msg.get("message_type") != "text":
                return None
            return PrivateMessage(
                event_id=header["event_id"],
                message_id=msg["message_id"],
                sender_id=sender["sender_id"]["open_id"],
                chat_id=msg["chat_id"],
                text=json.loads(msg["content"])["text"],
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
            AttributeError,
            RecursionError,
        ):
            raise ValueError("Invalid Feishu event") from None

    async def _access_token(self):
        async with self._token_lock:
            if self._token_until > time.monotonic():
                return self._token
            try:
                response = await self.client.post(
                    "/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self.config.app_id,
                        "app_secret": secret(self.config.app_secret_env),
                    },
                )
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("invalid token response")
                if response.status_code != 200 or data.get("code") != 0:
                    raise DeliveryError("failed", "feishu.credentials")
                token = data["tenant_access_token"]
                if not isinstance(token, str) or not token:
                    raise ValueError("invalid token")
                self._token = token
                self._token_until = time.monotonic() + max(0, int(data["expire"]) - 120)
                return token
            except (httpx.HTTPError, ValueError, KeyError):
                raise DeliveryError("retry", "feishu.token_unavailable") from None

    async def probe(self):
        await self._access_token()

    async def send(self, chat_id, text, delivery_id):
        token = await self._access_token()
        try:
            response = await self.client.post(
                "/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": "Bearer " + token},
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                    "uuid": delivery_id,
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise DeliveryError("retry", "feishu.not_connected") from None
        except httpx.HTTPError:
            raise DeliveryError("unknown", "feishu.send_unknown") from None
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("invalid receipt response")
            if response.status_code == 429 or data.get("code") == 99991400:
                try:
                    delay = min(
                        3600, max(1, float(response.headers.get("retry-after", 5)))
                    )
                except ValueError:
                    delay = 5
                raise DeliveryError("retry", "feishu.rate_limited", delay)
            if data.get("code") in (99991663, 99991664, 99991668):
                self._token_until = 0
                raise DeliveryError("retry", "feishu.token_expired")
            if response.status_code >= 500:
                raise DeliveryError("unknown", "feishu.server_error")
            if response.status_code != 200 or data.get("code") != 0:
                raise DeliveryError("failed", "feishu.rejected")
            receipt = data["data"]["message_id"]
            if not isinstance(receipt, str) or not receipt:
                raise ValueError("invalid receipt")
            return receipt
        except (ValueError, KeyError, TypeError):
            raise DeliveryError("unknown", "feishu.invalid_receipt") from None

    async def close(self):
        await self.client.aclose()


class FeishuFactory:
    def create(self, config):
        return FeishuChannel(FeishuConfig.model_validate(config))


def registration():
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="com.sage.im.feishu",
            version="1.0.0",
            name="Feishu IM",
            provides=(
                CapabilityOffer(
                    capability="im.channel-factory", api_version="1", name="feishu"
                ),
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema={"type": "object", "additionalProperties": False},
        ),
        factory=lambda context, deps: FeishuFactory(),
    )
