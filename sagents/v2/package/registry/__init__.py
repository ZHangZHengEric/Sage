"""Package lifecycle contracts and lazily exported registry plugins."""

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
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
