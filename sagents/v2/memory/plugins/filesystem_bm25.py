"""Durable per-scope MemoryProvider with established BM25 retrieval.

The established SAgents retrieval path uses BM25 for workspace and conversation
recall. This plugin applies that ranking family to long-term Memory records
without making SessionStore a second backend.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from rank_bm25 import BM25Okapi

from sagents.v2.memory.contracts import (
    MemoryCapabilities,
    MemoryDeleteResult,
    MemoryHit,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryWriteResult,
)


class FilesystemBm25MemoryProvider:
    """Store JSON records per scope and rank recall with BM25."""

    api_version = "2"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def capabilities(self) -> MemoryCapabilities:
        return MemoryCapabilities(
            durable=True,
            supports_filtering=True,
            supports_delete=True,
        )

    async def recall(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        async with self._lock:
            records = await asyncio.to_thread(self._read_scope, query.scope)
        if query.kinds:
            allowed = set(query.kinds)
            records = [record for record in records if record.kind in allowed]
        if query.metadata:
            records = [
                record
                for record in records
                if all(
                    record.metadata.get(key) == value
                    for key, value in query.metadata.items()
                )
            ]
        if not records:
            return ()
        query_tokens = self._tokenize(query.text)
        corpus = [self._tokenize(self._search_text(record)) for record in records]
        if not query_tokens or not any(corpus):
            return ()
        scores = BM25Okapi(corpus).get_scores(query_tokens)
        ranked = sorted(
            zip(records, scores, strict=True),
            key=lambda value: (float(value[1]), value[0].updated_at),
            reverse=True,
        )
        positive = [value for value in ranked if float(value[1]) > 0]
        selected = (positive or ranked)[: query.limit]
        maximum = max((float(score) for _, score in selected), default=1.0) or 1.0
        return tuple(
            MemoryHit(
                record=record,
                score=max(0.0, float(score) / maximum),
                reason="bm25",
            )
            for record, score in selected
        )

    async def remember(self, record: MemoryRecord) -> MemoryWriteResult:
        path = self._record_path(record.scope, record.memory_id)
        async with self._lock:
            created = not path.exists()
            await asyncio.to_thread(
                self._atomic_write, path, record.model_dump(mode="json")
            )
        return MemoryWriteResult(memory_id=record.memory_id, created=created)

    async def forget(self, memory_id: str, *, scope: MemoryScope) -> MemoryDeleteResult:
        path = self._record_path(scope, memory_id)
        async with self._lock:
            try:
                await asyncio.to_thread(path.unlink)
                deleted = True
            except FileNotFoundError:
                deleted = False
        return MemoryDeleteResult(memory_id=memory_id, deleted=deleted)

    async def get(self, memory_id: str, *, scope: MemoryScope) -> MemoryRecord | None:
        path = self._record_path(scope, memory_id)
        async with self._lock:
            if not path.exists():
                return None
            payload = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return MemoryRecord.model_validate_json(payload)

    async def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "provider": "filesystem-bm25",
            "root": str(self.root),
            "writable": os.access(self.root, os.W_OK),
        }

    def _scope_path(self, scope: MemoryScope) -> Path:
        encoded = json.dumps(
            scope.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self.root / "scopes" / hashlib.sha256(encoded).hexdigest()

    def _record_path(self, scope: MemoryScope, memory_id: str) -> Path:
        return self._scope_path(scope) / f"{quote(memory_id, safe='')}.json"

    def _read_scope(self, scope: MemoryScope) -> list[MemoryRecord]:
        directory = self._scope_path(scope)
        if not directory.exists():
            return []
        return [
            MemoryRecord.model_validate_json(path.read_text("utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]

    @staticmethod
    def _search_text(record: MemoryRecord) -> str:
        return " ".join(
            (
                record.content,
                record.kind,
                json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
            )
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text.lower())
        tokens: list[str] = []
        for word in normalized.split():
            if re.search(r"[\u4e00-\u9fff]", word):
                tokens.extend(re.findall(r"[\u4e00-\u9fff]", word))
                tokens.extend(re.findall(r"[a-z]+", word))
            elif len(word) > 1:
                tokens.append(word)
        return tokens

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
