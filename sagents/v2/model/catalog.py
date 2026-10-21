"""App-owned model configuration; Packages contain only model IDs.

Catalog changes publish immutable values. A compiled Agent owns its selected
routes, so neither updates nor unrelated catalog entries change admitted Runs.
"""
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.package.strict_yaml import load_unique_yaml


class ModelCatalogConfig(StrictModel):
    models: dict[Identifier, ModelRoute] = Field(default_factory=dict)
    credentials: dict[Identifier, CredentialDeclaration] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self):
        for model_id, route in self.models.items():
            if route.credential is not None and route.credential not in self.credentials:
                raise ValueError(f"model {model_id!r} references unknown App credential {route.credential!r}")
        return self

    def selected(self, model_ids):
        model_ids = set(model_ids)
        unknown = model_ids - self.models.keys()
        if unknown:
            raise ValueError(f"unknown App model IDs: {', '.join(sorted(unknown))}")
        routes = {key: self.models[key] for key in sorted(set(model_ids))}
        credentials = {route.credential: self.credentials[route.credential]
                       for route in routes.values() if route.credential is not None}
        return ModelCatalogConfig(models=routes, credentials=credentials).model_copy(deep=True)


ModelCatalogInput = ModelCatalogConfig | str | Path | dict[str, Any]


def model_catalog_input(value: ModelCatalogInput | None = None, *, config_text: str | None = None) -> ModelCatalogConfig:
    if value is not None and config_text is not None:
        raise ValueError("models and models_config_text are mutually exclusive")
    if isinstance(value, (str, Path)):
        config_text = Path(value).expanduser().read_text(encoding="utf-8")
    if config_text is not None:
        value = load_unique_yaml(config_text)
        if not isinstance(value, dict):
            raise ValueError("models config must be a mapping")
    return ModelCatalogConfig.model_validate(value if value is not None else {}).model_copy(deep=True)
