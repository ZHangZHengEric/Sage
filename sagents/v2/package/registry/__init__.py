"""Package lifecycle contracts and lazily exported registry plugins."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.package.registry.contracts import AgentPackageRecord as AgentPackageRecord
    from sagents.v2.package.registry.contracts import PackageStage as PackageStage
    from sagents.v2.package.registry.contracts import PackageValidationReport as PackageValidationReport
    from sagents.v2.package.registry.plugins.ephemeral import InMemoryAgentPackageRegistry as InMemoryAgentPackageRegistry


from sagents.v2._lazy import exported_names, resolve_export


_CONTRACTS = "sagents.v2.package.registry.contracts"
_EXPORTS = {
    "AgentPackageRecord": (_CONTRACTS, "AgentPackageRecord"),
    "PackageStage": (_CONTRACTS, "PackageStage"),
    "PackageValidationReport": (_CONTRACTS, "PackageValidationReport"),
    "InMemoryAgentPackageRegistry": (
        "sagents.v2.package.registry.plugins.ephemeral",
        "InMemoryAgentPackageRegistry",
    ),
}
__all__ = [
    "AgentPackageRecord",
    "PackageStage",
    "PackageValidationReport",
    "InMemoryAgentPackageRegistry",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
