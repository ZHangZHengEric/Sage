"""SAgents V2 module for runtime/credentials/__init__.py."""

from sagents.v2._lazy import exported_names, resolve_export

from sagents.v2.runtime.credentials.contracts import (
    CredentialMaterial,
    CredentialRef,
)
from sagents.v2.runtime.credentials.provider import CredentialProvider

_LAZY_EXPORTS = {
    "EnvironmentCredentialProvider": (
        "sagents.v2.runtime.credentials.plugins.environment",
        "EnvironmentCredentialProvider",
    ),
    "MappingCredentialProvider": (
        "sagents.v2.runtime.credentials.plugins.mapping",
        "MappingCredentialProvider",
    ),
}

__all__ = [
    "CredentialMaterial",
    "CredentialProvider",
    "CredentialRef",
    "EnvironmentCredentialProvider",
    "MappingCredentialProvider",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
