from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr
from sagents.v2.contracts.common import new_id
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    resolve_model_protocol,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.credentials.contracts import CredentialMaterial

from app.server_v2.core.errors import ServerV2Error


class ModelRecord(BaseModel):
    id: str
    protocol: str = "openai-chat-completions"
    base_url: str = "https://api.openai.com/v1"
    model: str
    api_key: SecretStr
    is_default: bool = True

    def cache_key(self) -> str:
        return "|".join(
            (
                self.id,
                self.protocol,
                self.base_url,
                self.model,
                self.api_key.get_secret_value(),
            )
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
            "is_default": self.is_default,
        }

    def to_provider(self) -> ModelProvider:
        route = ModelRoute(
            provider=resolve_model_protocol(self.protocol).value,
            base_url=self.base_url,
            model=self.model,
        )
        credential = CredentialMaterial(
            credential_id=f"catalog-{self.id}",
            secret=self.api_key,
            source="host",
        )
        return create_registered_model_provider(route, credential)


class AgentRecord(BaseModel):
    id: str
    name: str
    instructions: str = ""
    skills: list[str] = Field(default_factory=list)


class UserCatalog(BaseModel):
    agents: list[AgentRecord] = Field(default_factory=list)
    models: list[ModelRecord] = Field(default_factory=list)


def empty_catalog() -> UserCatalog:
    return UserCatalog(agents=[AgentRecord(id="main", name="Main Assistant")])


def catalog_payload(catalog: UserCatalog) -> dict[str, object]:
    payload = catalog.model_dump(mode="json")
    for item, record in zip(payload.get("models", []), catalog.models):
        item["api_key"] = record.api_key.get_secret_value()
    return payload


def apply_upsert(
    catalog: UserCatalog, payload: dict[str, object]
) -> tuple[ModelRecord, UserCatalog]:
    model_id = str(payload.get("id") or new_id("model"))
    protocol = str(payload.get("protocol") or "openai-chat-completions")
    resolve_model_protocol(protocol)
    record = ModelRecord(
        id=model_id,
        protocol=protocol,
        base_url=str(payload.get("base_url") or "https://api.openai.com/v1"),
        model=str(payload.get("model") or "").strip(),
        api_key=SecretStr(str(payload.get("api_key") or "")),
        is_default=bool(payload.get("is_default", False) or not catalog.models),
    )
    if not record.model:
        raise ServerV2Error("validation", "model is required")
    if not record.api_key.get_secret_value():
        existing = next((item for item in catalog.models if item.id == model_id), None)
        if existing is None:
            raise ServerV2Error("validation", "api_key is required")
        record = record.model_copy(update={"api_key": existing.api_key})
    models = [
        item.model_copy(update={"is_default": False}) if record.is_default else item
        for item in catalog.models
        if item.id != model_id
    ]
    models.append(record)
    catalog.models = models
    return record, catalog


def apply_delete(catalog: UserCatalog, model_id: str) -> UserCatalog:
    remaining = [item for item in catalog.models if item.id != model_id]
    if len(remaining) == len(catalog.models):
        raise ServerV2Error("not_found", "model not found")
    if remaining and not any(item.is_default for item in remaining):
        remaining[0] = remaining[0].model_copy(update={"is_default": True})
    catalog.models = remaining
    return catalog
