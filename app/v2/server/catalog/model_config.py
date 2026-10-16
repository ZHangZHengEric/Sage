"""Translate the tenant model directory into the SDK's App configuration."""
from sagents.v2.model.catalog import ModelCatalogConfig
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.package.manifest.credentials import CredentialDeclaration


def app_models(catalog):
    models, credentials = {}, {}
    for record in catalog.models:
        key = f"server-model:{record.id}"
        credentials[key] = CredentialDeclaration(source="host", ref=record.id)
        models[record.id] = record.route().model_copy(update={"credential": key})
    default = next((item for item in catalog.models if item.is_default), None)
    default = default or next(iter(catalog.models), None)
    models["default"] = models[default.id] if default else ModelRoute(provider="server", model="default")
    return ModelCatalogConfig(models=models, credentials=credentials)
