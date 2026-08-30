"""Checksummed records used by :class:`FilesystemSessionStore`.

Version 1 appended a complete Session aggregate for every accepted mutation.
Version 2 atomically replaced that aggregate on every mutation. Version 3 uses
a compact snapshot plus a checksummed incremental journal. Older envelopes
remain available to the forward readers.
"""

from __future__ import annotations

from typing import Any, Literal

from sagents.v2.contracts.common import StrictModel


FILESYSTEM_SESSION_STORE_FORMAT_V1: Literal["sage.filesystem-session-store/v1"] = (
    "sage.filesystem-session-store/v1"
)
FILESYSTEM_SESSION_STORE_FORMAT_V2: Literal["sage.filesystem-session-store/v2"] = (
    "sage.filesystem-session-store/v2"
)
FILESYSTEM_SESSION_STORE_FORMAT: Literal["sage.filesystem-session-store/v3"] = (
    "sage.filesystem-session-store/v3"
)


class SessionCommitEnvelope(StrictModel):
    """Legacy v1 append-only full-state record, used only for migration."""

    format: Literal["sage.filesystem-session-store/v1"] = (
        FILESYSTEM_SESSION_STORE_FORMAT_V1
    )
    transaction_id: str
    journal_sequence: int
    previous_session_revision: int
    current_session_revision: int
    state: dict[str, Any]
    checksum: str


class SessionSnapshotEnvelope(StrictModel):
    """Compact v3 base state for one Session."""

    format: Literal["sage.filesystem-session-store/v3"] = (
        FILESYSTEM_SESSION_STORE_FORMAT
    )
    write_id: str
    current_session_revision: int
    state: dict[str, Any]
    checksum: str


class SessionSnapshotEnvelopeV2(StrictModel):
    """Legacy v2 atomically replaced aggregate, used for forward migration."""

    format: Literal["sage.filesystem-session-store/v2"] = (
        FILESYSTEM_SESSION_STORE_FORMAT_V2
    )
    write_id: str
    current_session_revision: int
    state: dict[str, Any]
    checksum: str


class SessionMutationEnvelope(StrictModel):
    """One revision-contiguous mutation appended after the compact snapshot."""

    format: Literal["sage.filesystem-session-journal/v3"] = (
        "sage.filesystem-session-journal/v3"
    )
    mutation_id: str
    previous_session_revision: int
    current_session_revision: int
    delta: dict[str, Any]
    checksum: str
