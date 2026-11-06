"""Operator-owned routes; an IM message cannot select a tenant or credential."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    platform_id: str = Field(min_length=1, max_length=192)
    api_key_env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    allowed_sender_ids: list[str] = Field(min_length=1)
    allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def remove_template_marker(cls, value):
        # AstrBot adds this field to entries created by a template_list schema.
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "__template_key"}
        return value

    @field_validator("allowed_sender_ids", "allowed_origins")
    @classmethod
    def validate_identifiers(cls, values: list[str]) -> list[str]:
        if any(not item.strip() or item != item.strip() for item in values):
            raise ValueError(
                "identifiers must be nonempty and have no surrounding whitespace"
            )
        return values


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    server_url: str = "http://sage:8090"
    request_timeout_seconds: float = Field(default=30, gt=0, le=120)
    wait_seconds: float = Field(default=15, ge=0, le=60)
    poll_interval_seconds: float = Field(default=1, gt=0, le=10)
    max_image_bytes: int = Field(default=4_194_304, gt=0, le=16_777_216)
    bindings: list[Binding] = Field(default_factory=list)

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or re.search(r"\s", value)
        ):
            raise ValueError(
                "server_url must be an http(s) URL without credentials, query or fragment"
            )
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("invalid server port") from exc
        return value.rstrip("/")

    @model_validator(mode="after")
    def unique_platforms(self):
        ids = [binding.platform_id for binding in self.bindings]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "each AstrBot platform instance must have exactly one binding"
            )
        return self
