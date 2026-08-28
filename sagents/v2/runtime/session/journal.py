"""Checksummed append-only records used by FilesystemSessionStore."""

from __future__ import annotations

from typing import Any, Literal

from sagents.v2.contracts.common import StrictModel


FILESYSTEM_SESSION_STORE_FORMAT: Literal["sage.filesystem-session-store/v1"] = (
    "sage.filesystem-session-store/v1"
)


class SessionCommitEnvelope(StrictModel):
    """One durable, atomic version of a single Session aggregate.

    The reference file plugin stores a complete aggregate in every envelope.
    This intentionally favors auditability and unambiguous crash recovery over
    write amplification. A database plugin may use normalized deltas while
    preserving the same SessionStore semantics.
    """

    format: Literal["sage.filesystem-session-store/v1"] = (
        FILESYSTEM_SESSION_STORE_FORMAT
    )
    transaction_id: str
    journal_sequence: int
    previous_session_revision: int
    current_session_revision: int
    state: dict[str, Any]
    checksum: str
