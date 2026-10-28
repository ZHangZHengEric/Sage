"""IM management responses; platform Webhook responses retain Feishu's format."""

from typing import Any, Literal

from pydantic import BaseModel


class IMConfigPublic(BaseModel):
    app_id: str
    tenant_key: str


class IMConnectionPublic(BaseModel):
    id: str
    name: str
    plugin: Literal["com.sage.im.feishu"]
    owner_user_id: str
    agent_id: str
    config: IMConfigPublic
    credentials_configured: bool
    credentials_error: str
    enabled: bool
    revision: int
    paired: bool
    webhook_url: str


class IMConnectionPage(BaseModel):
    items: list[IMConnectionPublic]
    next_cursor: str | None = None


class IMPluginPublic(BaseModel):
    id: str
    name: str
    config_schema: dict[str, Any]
    capabilities: list[str]


class IMPluginPage(BaseModel):
    items: list[IMPluginPublic]
    next_cursor: str | None = None


class IMPairingPublic(BaseModel):
    code: str
    expires_in: int
    command: str


class IMStatusPublic(BaseModel):
    state: Literal["unavailable", "disabled", "awaiting_pairing", "webhook_ready"]
    revision: int
    paired: bool


class IMDeliveryPublic(BaseModel):
    id: int
    revision: int
    state: Literal[
        "pending", "sending", "platform_accepted", "failed", "unknown", "superseded"
    ]
    attempts: int
    error: str
    receipt: str


class IMDeliveryPage(BaseModel):
    items: list[IMDeliveryPublic]
    next_cursor: int | None = None
