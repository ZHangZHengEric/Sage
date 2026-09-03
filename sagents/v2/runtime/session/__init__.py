"""Session contracts and lazily loaded implementations."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "AuthorizedSessionAccess": (
        "sagents.v2.runtime.session.access",
        "AuthorizedSessionAccess",
    ),
    "CommitResult": ("sagents.v2.runtime.session.contracts", "CommitResult"),
    "DerivedStateStore": (
        "sagents.v2.runtime.session.contracts",
        "DerivedStateStore",
    ),
    "DispatchableRun": (
        "sagents.v2.runtime.session.contracts",
        "DispatchableRun",
    ),
    "EphemeralSessionStore": (
        "sagents.v2.runtime.session.plugins.ephemeral",
        "EphemeralSessionStore",
    ),
    "EventDraft": ("sagents.v2.runtime.session.contracts", "EventDraft"),
    "FilesystemSessionStore": (
        "sagents.v2.runtime.session.plugins.filesystem",
        "FilesystemSessionStore",
    ),
    "InMemoryDerivedStateStore": (
        "sagents.v2.runtime.session.derived_state",
        "InMemoryDerivedStateStore",
    ),
    "LeaseFencedSessionStore": (
        "sagents.v2.runtime.session.fencing",
        "LeaseFencedSessionStore",
    ),
    "MigrationReport": (
        "sagents.v2.runtime.session.migration",
        "MigrationReport",
    ),
    "MysqlSessionStore": (
        "sagents.v2.runtime.session.plugins.mysql",
        "MysqlSessionStore",
    ),
    "PostgresSessionStore": (
        "sagents.v2.runtime.session.plugins.postgres",
        "PostgresSessionStore",
    ),
    "RunCreationResult": (
        "sagents.v2.runtime.session.contracts",
        "RunCreationResult",
    ),
    "SessionAggregate": (
        "sagents.v2.runtime.session.aggregate",
        "SessionAggregate",
    ),
    "SessionStore": ("sagents.v2.runtime.session.contracts", "SessionStore"),
    "SessionStoreCoordinator": (
        "sagents.v2.runtime.session.coordinator",
        "SessionStoreCoordinator",
    ),
    "SessionStoreCorruptionError": (
        "sagents.v2.runtime.session.plugins.filesystem",
        "SessionStoreCorruptionError",
    ),
    "SteerClaimResult": (
        "sagents.v2.runtime.session.contracts",
        "SteerClaimResult",
    ),
    "StoreInUseError": (
        "sagents.v2.runtime.session.plugins.filesystem",
        "StoreInUseError",
    ),
    "SubscriptionHub": (
        "sagents.v2.runtime.session.subscriptions",
        "SubscriptionHub",
    ),
    "migrate_manifest_v1": (
        "sagents.v2.runtime.session.migration",
        "migrate_manifest_v1",
    ),
    "migrate_runtime_root": (
        "sagents.v2.runtime.session.migration",
        "migrate_runtime_root",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
