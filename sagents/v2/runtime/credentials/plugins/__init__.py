"""Official credential provider plugins."""

from sagents.v2.runtime.credentials.plugins.environment import (
    EnvironmentCredentialProvider,
)
from sagents.v2.runtime.credentials.plugins.mapping import MappingCredentialProvider

__all__ = ["EnvironmentCredentialProvider", "MappingCredentialProvider"]
