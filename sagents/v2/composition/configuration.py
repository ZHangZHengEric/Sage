"""Registration and selection data for standard managed/isolated Apps."""
from dataclasses import dataclass
from typing import Any

from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions import ExtensionRegistration


@dataclass(frozen=True)
class ApplicationConfiguration:
    """A host describes capabilities; Sage performs the standard build sequence.

    Process objects live only in registration factories. Runtime/model selection
    remains serializable, and this value exposes no execution replacement port.
    """
    registrations: tuple[ExtensionRegistration, ...]
    runtime: RuntimeConfig
    models: Any = None
