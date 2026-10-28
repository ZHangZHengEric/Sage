"""Host channel contracts. Platform input never carries Sage authorization."""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

GRANT_KEY = "server_v2.im"
NOTIFY_KEY = "server_v2.im_notify"


class NotificationRoute(BaseModel):
    """Server-issued, frozen destination; never accepted as model arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_id: str
    agent_id: str
    connection_id: str
    binding_id: str
    generation: int = Field(ge=1)
    auth_epoch: int = Field(ge=1)
    sender_id: str
    chat_id: str


class PrivateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str = Field(min_length=1, max_length=192)
    message_id: str = Field(min_length=1, max_length=192)
    sender_id: str = Field(min_length=1, max_length=192)
    chat_id: str = Field(min_length=1, max_length=192)
    text: str = Field(max_length=20000)


@dataclass
class DeliveryError(Exception):
    outcome: Literal["retry", "failed", "unknown"]
    code: str
    retry_after: float = 5


class Channel(Protocol):
    def decode(self, body: bytes, headers: dict) -> PrivateMessage | dict | None: ...
    async def send(self, chat_id: str, text: str, delivery_id: str) -> str: ...
    async def close(self) -> None: ...
