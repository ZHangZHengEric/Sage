"""Official Feishu SDK transport. Sage owns admission, Run and delivery state."""

import asyncio
import json
import time
from urllib.parse import urlsplit

import httpx
import lark_oapi as lark
from lark_oapi.api.auth.v3 import (
    InternalTenantAccessTokenRequest,
    InternalTenantAccessTokenRequestBody,
)
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from .contracts import DeliveryError, PrivateMessage
from .feishu_ws import SDKReceiver


class FeishuConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    app_id: str = Field(pattern=r"^cli_[A-Za-z0-9_]+$", max_length=128)
    app_secret: SecretStr = Field(min_length=1, max_length=512)
    web_url: str = Field(default="", max_length=2048)

    @field_validator("web_url")
    @classmethod
    def valid_web_url(cls, value):
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("invalid Sage web URL")
        return value.rstrip("/")

    def request_payload(self):
        return {
            **self.model_dump(mode="json", exclude={"app_secret"}),
            "app_secret": self.app_secret.get_secret_value(),
        }


class FeishuChannel:
    def __init__(self, config: FeishuConfig):
        self.config = config
        self.client = (
            lark.Client.builder()
            .app_id(config.app_id)
            .app_secret(config.app_secret.get_secret_value())
            .enable_set_token(True)
            .timeout(15)
            .log_level(lark.LogLevel.CRITICAL)
            .build()
        )
        self._token, self._token_until = "", 0
        self._token_lock = asyncio.Lock()
        self._task = None
        self.receiver = None
        self.state = "disconnected"

    @property
    def receiving(self):
        return self._task is not None

    def normalize(self, payload):
        """Only called for an event delivered on this app's authenticated socket."""
        try:
            header, event = payload["header"], payload["event"]
            if header.get("app_id") != self.config.app_id:
                raise ValueError("wrong app")
            tenant = header.get("tenant_key")
            if not isinstance(tenant, str) or not tenant:
                raise ValueError("missing tenant")
            sender, msg = event["sender"], event["message"]
            if sender.get("tenant_key") != tenant:
                raise ValueError("wrong tenant")
            if (
                sender.get("sender_type") != "user"
                or msg.get("chat_type") != "p2p"
                or msg.get("message_type") != "text"
            ):
                return None
            return PrivateMessage(
                event_id=header["event_id"],
                message_id=msg["message_id"],
                sender_id=sender["sender_id"]["open_id"],
                chat_id=msg["chat_id"],
                text=json.loads(msg["content"])["text"],
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("Invalid Feishu event") from None

    async def start(self, admit):
        self._admit = admit
        if self._task is not None:
            return

        async def receive(payload):
            message = self.normalize(payload)
            if message is not None:
                await self._admit(message)

        self.receiver = SDKReceiver(
            self.config, receive, lambda value: setattr(self, "state", value)
        )
        self._task = asyncio.create_task(
            self.receiver.run(), name="feishu-sdk-connection"
        )

    async def _access_token(self):
        async with self._token_lock:
            if self._token_until > time.monotonic():
                return self._token
            try:
                request = (
                    InternalTenantAccessTokenRequest.builder()
                    .request_body(
                        InternalTenantAccessTokenRequestBody.builder()
                        .app_id(self.config.app_id)
                        .app_secret(self.config.app_secret.get_secret_value())
                        .build()
                    )
                    .build()
                )
                response = await self.client.auth.v3.tenant_access_token.ainternal(
                    request
                )
                if response.raw.status_code != 200 or not response.success():
                    raise DeliveryError(
                        "retry"
                        if response.raw.status_code >= 500
                        or response.raw.status_code == 429
                        else "failed",
                        "feishu.credentials",
                    )
                # The endpoint returns token fields at the top level; the
                # generated SDK response model incorrectly nests them in data.
                data = json.loads(response.raw.content)
                token, expiry = data["tenant_access_token"], data["expire"]
                if (
                    not isinstance(token, str)
                    or not token
                    or not isinstance(expiry, int)
                ):
                    raise ValueError("invalid token")
                self._token, self._token_until = (
                    token,
                    time.monotonic() + max(0, expiry - 120),
                )
                return token
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                raise DeliveryError("retry", "feishu.token_unavailable") from None

    async def probe(self):
        self._token_until = 0
        await self._access_token()

    async def send(self, chat_id, text, delivery_id):
        token = await self._access_token()
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .uuid(delivery_id)
                .build()
            )
            .build()
        )
        option = lark.RequestOption.builder().tenant_access_token(token).build()
        try:
            response = await self.client.im.v1.message.acreate(request, option)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise DeliveryError("retry", "feishu.not_connected") from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise DeliveryError("unknown", "feishu.send_unknown") from None
        status = response.raw.status_code
        if status == 429 or response.code == 99991400:
            try:
                delay = min(
                    3600, max(1, float(response.raw.headers.get("retry-after", 5)))
                )
            except (TypeError, ValueError):
                delay = 5
            raise DeliveryError("retry", "feishu.rate_limited", delay)
        if response.code in (99991663, 99991664, 99991668):
            self._token_until = 0
            raise DeliveryError("retry", "feishu.token_expired")
        if status >= 500:
            raise DeliveryError("unknown", "feishu.server_error")
        if status != 200 or not response.success():
            raise DeliveryError("failed", "feishu.rejected")
        receipt = getattr(response.data, "message_id", None)
        if not isinstance(receipt, str) or not receipt:
            raise DeliveryError("unknown", "feishu.invalid_receipt")
        return receipt

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self.receiver is not None:
            await self.receiver.close()
            self.receiver = None
        self.state = "disconnected"


class FeishuFactory:
    def create(self, config):
        return FeishuChannel(FeishuConfig.model_validate(config))


def registration():
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="com.sage.im.feishu",
            version="2.0.0",
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
