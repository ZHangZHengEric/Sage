"""Storage contracts for durable agent session data.

The methods describe domain operations rather than filesystem operations so a
backend does not need to emulate directories, renames, or JSON files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence


class StorageError(RuntimeError):
    """Base error raised by a session persistence backend."""


class StorageConflictError(StorageError):
    """A conditional update lost a race with another writer."""


class SessionNotFoundError(StorageError):
    """The requested session has no durable record in the backend."""


@dataclass(frozen=True)
class MessageLedger:
    messages: list[dict[str, Any]]
    max_sequence: int = 0
    journal_records: int = 0


class SessionStore(ABC):
    """Synchronous persistence contract used by the session runtime.

    Runtime callers that must not block the event loop execute these methods in
    a worker thread. Implementations must be safe for concurrent sessions.
    """

    @property
    @abstractmethod
    def root(self) -> str:
        """Backend namespace used for this set of sessions."""

    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def healthcheck(self) -> Mapping[str, Any]: ...

    # Session catalog -------------------------------------------------
    @abstractmethod
    def register_session(
        self,
        session_id: str,
        workspace: str,
        parent_session_id: Optional[str] = None,
    ) -> None: ...

    @abstractmethod
    def register_sessions(
        self, entries: Iterable[tuple[str, str, Optional[str]]]
    ) -> None: ...

    @abstractmethod
    def get_session_workspace(self, session_id: str) -> Optional[str]: ...

    @abstractmethod
    def session_exists(self, session_id: str) -> bool: ...

    @abstractmethod
    def get_parent_session_id(self, session_id: str) -> Optional[str]: ...

    @abstractmethod
    def remove_session(self, session_id: str) -> None: ...

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete a session and all of its durable descendant data."""
        ...

    @abstractmethod
    def list_sessions(self) -> Mapping[str, str]: ...

    @abstractmethod
    def migrate_legacy_sessions(self) -> int:
        """Import records from this backend's legacy representation, if any."""
        ...

    # Authoritative state --------------------------------------------
    @abstractmethod
    def create_session_workspace(
        self,
        session_id: str,
        *,
        parent_workspace: Optional[str] = None,
    ) -> str: ...

    @abstractmethod
    def bind_session_workspace(self, session_id: str, workspace: str) -> None:
        """Bind an already resolved physical workspace for this process.

        This preserves compatibility for restored and embedded sessions while
        keeping path resolution inside the filesystem backend.
        """
        ...

    @abstractmethod
    def load_session_snapshot(self, session_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def save_session_snapshot(
        self, session_id: str, snapshot: Mapping[str, Any]
    ) -> str: ...

    @abstractmethod
    def load_message_ledger(self, session_id: str) -> MessageLedger: ...

    @abstractmethod
    def append_message_event(
        self, session_id: str, event: Mapping[str, Any]
    ) -> str: ...

    @abstractmethod
    def save_message_snapshot(
        self, session_id: str, messages: Sequence[Mapping[str, Any]]
    ) -> str: ...

    @abstractmethod
    def clear_message_events(self, session_id: str) -> None: ...

    @abstractmethod
    def message_events_have_records(self, session_id: str) -> bool: ...

    # Derived state ---------------------------------------------------
    @abstractmethod
    def save_compact_manifest(
        self, session_id: str, manifest: Mapping[str, Any]
    ) -> str: ...

    @abstractmethod
    def save_tools_usage(
        self, session_id: str, usage: Mapping[str, int]
    ) -> str: ...

    @abstractmethod
    def load_tools_usage(self, session_id: str) -> Mapping[str, int]: ...

    @abstractmethod
    def append_session_log(self, session_id: str, text: str) -> str:
        """Append already formatted diagnostic text for one session."""
        ...

    @abstractmethod
    def read_session_log_tail(self, session_id: str, *, max_bytes: int) -> str:
        """Return up to the most recent ``max_bytes`` of diagnostic text."""
        ...

    # Audit / telemetry ----------------------------------------------
    @abstractmethod
    def append_llm_request(
        self, session_id: str, record: Mapping[str, Any]
    ) -> str: ...

    @abstractmethod
    def save_request_usage(
        self, session_id: str, request_id: str, usage: Mapping[str, Any]
    ) -> str: ...

    @abstractmethod
    def save_mcp_calls(
        self, session_id: str, request_id: str, payload: Mapping[str, Any]
    ) -> str: ...

    @abstractmethod
    def purge_llm_requests(self, *, before: float) -> Mapping[str, int]: ...

    @abstractmethod
    def purge_sessions(
        self, *, before: float, session_id_prefix: str
    ) -> Mapping[str, int]: ...

    @abstractmethod
    def export_session_archive(self, session_id: str) -> str:
        """Export one session into a backend-produced local archive."""
        ...
