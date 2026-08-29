"""SAgents V2 module for interfaces/protocols/__init__.py."""

from sagents.v2.interfaces.protocols.contracts import (
    AdapterCapabilities,
    AdapterResult,
    LossReport,
    MappingFidelity,
    ProtocolFrame,
)
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter

__all__ = [
    "AdapterCapabilities",
    "AdapterResult",
    "LossReport",
    "MappingFidelity",
    "NativeProtocolAdapter",
    "ProtocolFrame",
]
