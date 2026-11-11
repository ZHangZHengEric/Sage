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
