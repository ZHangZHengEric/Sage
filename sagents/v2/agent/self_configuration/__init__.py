"""Host-authorized, immediately usable Agent capability additions."""

from sagents.v2.agent.self_configuration.service import (
    SelfConfigurationService,
    SelfConfigurationRequest,
)
from sagents.v2.agent.self_configuration.store import SqliteSelfConfigurationStore

__all__ = [
    "SelfConfigurationService",
    "SelfConfigurationRequest",
    "SqliteSelfConfigurationStore",
]
