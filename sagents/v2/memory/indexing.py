"""Stable scope and indexed text for long-term BM25 memory."""

import hashlib
import json

from sagents.v2.memory.contracts import MemoryRecord, MemoryScope


def scope_key(scope: MemoryScope) -> str:
    encoded = json.dumps(
        scope.model_dump(mode="json", exclude={"workspace_id"} if scope.workspace_id is None else set()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def search_text(record: MemoryRecord) -> str:
    return " ".join(
        (
            record.content,
            record.kind,
            json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
        )
    )


def workspace_delete_filter(tenant_id, principal_id, workspace_id, private_scopes=()):
    """Match trusted workspace attribution and exact scopes from older Runs."""
    return (
        """
        json_extract(payload_json, '$.scope.tenant_id') = ?
        AND json_extract(payload_json, '$.scope.principal_id') = ?
        AND (
            json_extract(payload_json, '$.scope.workspace_id') = ?
            OR json_extract(payload_json, '$.source.root_workspace_id') = ?
            OR scope_key IN (SELECT value FROM json_each(?))
        )
        """,
        (tenant_id, principal_id, workspace_id, workspace_id,
         json.dumps(sorted({scope_key(scope) for scope in private_scopes}))),
    )
