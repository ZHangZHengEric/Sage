"""SAgents V2 module for runtime/credentials/__init__.py."""

from sagents.v2.runtime.credentials.contracts import (
    CredentialMaterial,
    CredentialRef,
)
from sagents.v2.runtime.credentials.provider import CredentialProvider
from sagents.v2.runtime.credentials.plugins import (
    EnvironmentCredentialProvider,
    MappingCredentialProvider,
)

__all__ = [
    "CredentialMaterial",
    "CredentialProvider",
    "CredentialRef",
    "EnvironmentCredentialProvider",
    "MappingCredentialProvider",
]
