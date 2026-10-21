"""Session contracts and lazily loaded implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore as RedisMysqlSessionStore
    from sagents.v2.runtime.session.access import AuthorizedSessionAccess as AuthorizedSessionAccess
    from sagents.v2.runtime.session.contracts import CommitResult as CommitResult
    from sagents.v2.runtime.session.contracts import DerivedStateStore as DerivedStateStore
    from sagents.v2.runtime.session.contracts import DispatchableRun as DispatchableRun
    from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore as EphemeralSessionStore
    from sagents.v2.runtime.session.contracts import EventDraft as EventDraft
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore as FilesystemSessionStore
    from sagents.v2.runtime.session.plugins.derived_ephemeral import InMemoryDerivedStateStore as InMemoryDerivedStateStore
    from sagents.v2.runtime.session.fencing import LeaseFencedSessionStore as LeaseFencedSessionStore
    from sagents.v2.runtime.session.migration import MigrationReport as MigrationReport
    from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore as MysqlSessionStore
    from sagents.v2.runtime.session.contracts import RunCreationResult as RunCreationResult
    from sagents.v2.runtime.session.aggregate import SessionAggregate as SessionAggregate
    from sagents.v2.runtime.session.contracts import SessionStore as SessionStore
    from sagents.v2.runtime.session.state import SessionStoreCoordinator as SessionStoreCoordinator
    from sagents.v2.runtime.session.plugins.filesystem import SessionStoreCorruptionError as SessionStoreCorruptionError
    from sagents.v2.runtime.session.contracts import SteerClaimResult as SteerClaimResult
    from sagents.v2.runtime.session.plugins.filesystem import StoreInUseError as StoreInUseError
    from sagents.v2.runtime.session.subscriptions import SubscriptionHub as SubscriptionHub
    from sagents.v2.runtime.session.migration import migrate_runtime_root as migrate_runtime_root


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "RedisMysqlSessionStore": (
        "sagents.v2.runtime.session.plugins.mysql.redis", "RedisMysqlSessionStore",
    ),
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
        "sagents.v2.runtime.session.plugins.derived_ephemeral",
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
        "sagents.v2.runtime.session.state",
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
    "migrate_runtime_root": (
        "sagents.v2.runtime.session.migration",
        "migrate_runtime_root",
    ),
}

__all__ = [
    "RedisMysqlSessionStore",
    "AuthorizedSessionAccess",
    "CommitResult",
    "DerivedStateStore",
    "DispatchableRun",
    "EphemeralSessionStore",
    "EventDraft",
    "FilesystemSessionStore",
    "InMemoryDerivedStateStore",
    "LeaseFencedSessionStore",
    "MigrationReport",
    "MysqlSessionStore",
    "RunCreationResult",
    "SessionAggregate",
    "SessionStore",
    "SessionStoreCoordinator",
    "SessionStoreCorruptionError",
    "SteerClaimResult",
    "StoreInUseError",
    "SubscriptionHub",
    "migrate_runtime_root",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
