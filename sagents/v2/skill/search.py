"""Local lexical index shared by Skill providers."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import BinaryIO

from sagents.v2.contracts.skill_payload import SkillDescriptor

MAX_SEARCH_BODY_BYTES = 64 * 1024
_HAN = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af"
_WORDS = re.compile(rf"[{_HAN}]+|[^\W_{_HAN}]+")
_FRONTMATTER = re.compile(rb"\A---[ \t]*\r?\n.*?^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.M | re.S)


def searchable_body(content: bytes) -> bytes:
    header = _FRONTMATTER.match(content)
    start = header.end() if header else 0
    return content[start:start + MAX_SEARCH_BODY_BYTES]


def read_searchable_body(stream: BinaryIO, *, limit: int = MAX_SEARCH_BODY_BYTES) -> bytes:
    """Skip frontmatter while reading at most one body-sized chunk at a time."""
    limit = min(limit, MAX_SEARCH_BODY_BYTES)
    start = stream.tell()
    first = stream.readline(limit)
    if not first.endswith(b"\n") or first.rstrip(b" \t\r\n") != b"---":
        return first + stream.read(limit - len(first))
    line_start = True
    while line := stream.readline(MAX_SEARCH_BODY_BYTES):
        line_end = line.endswith(b"\n") or len(line) < MAX_SEARCH_BODY_BYTES
        if line_start and line_end and line.rstrip(b" \t\r\n") in (b"---", b"..."):
            return stream.read(limit)
        line_start = line_end
    stream.seek(start)
    return stream.read(limit)


def _tokens(text: str) -> Iterable[str]:
    for match in _WORDS.finditer(unicodedata.normalize("NFKC", text).casefold()):
        word = match.group()
        if re.match(rf"[{_HAN}]", word) and len(word) > 1:
            yield from (word[i:i + 2] for i in range(len(word) - 1))
        else:
            yield word


def has_search_terms(query: str) -> bool:
    return next(iter(_tokens(query)), None) is not None


def create_index(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS skill_search_fts USING fts5(
            document_key UNINDEXED, descriptor UNINDEXED, name, description, body,
            tokenize='unicode61'
        )
    """)


def put_document(
    db: sqlite3.Connection, key: str, descriptor: SkillDescriptor, body: bytes,
) -> None:
    text = body.decode("utf-8", errors="ignore")
    db.execute(
        "INSERT INTO skill_search_fts VALUES (?, ?, ?, ?, ?)",
        (
            key, descriptor.model_dump_json(), " ".join(_tokens(descriptor.name)),
            " ".join(_tokens(descriptor.description)), " ".join(_tokens(text)),
        ),
    )


class ScopedSkillRanker:
    """Rank with BM25 statistics from the authorized corpus only.

    FTS5 computes statistics over the entire table even with a WHERE clause.
    Keep two connection-local projections of immutable indexed documents so
    alternating Run scopes can reuse their corpora.
    """

    def __init__(self) -> None:
        self._projections: OrderedDict[frozenset[str], int] = OrderedDict()

    def rank(
        self, db: sqlite3.Connection, query: str, keys: Iterable[str], limit: int,
        *, all_indexed: bool = False,
    ) -> tuple[SkillDescriptor, ...]:
        terms = dict.fromkeys(_tokens(query))
        allowed = frozenset(keys)
        if not terms or not allowed:
            return ()
        table = "skill_search_fts"
        if not all_indexed:
            slot = self._projections.get(allowed)
            if slot is None:
                evicted = next(iter(self._projections)) if len(self._projections) == 2 else None
                slot = self._projections[evicted] if evicted is not None else len(self._projections)
                table = f"authorized_skill_search_fts_{slot}"
                with db:
                    db.execute(f"""
                        CREATE VIRTUAL TABLE IF NOT EXISTS temp.{table} USING fts5(
                            document_key UNINDEXED, descriptor UNINDEXED, name, description, body,
                            tokenize='unicode61'
                        )
                    """)
                    db.execute(f"DELETE FROM temp.{table}")
                    db.execute(f"""
                        INSERT INTO temp.{table}
                        SELECT document_key, descriptor, name, description, body
                        FROM skill_search_fts
                        WHERE document_key IN (SELECT value FROM json_each(?))
                    """, (json.dumps(sorted(allowed)),))
                if evicted is not None:
                    del self._projections[evicted]
                self._projections[allowed] = slot
            else:
                table = f"authorized_skill_search_fts_{slot}"
                self._projections.move_to_end(allowed)

        rows = db.execute(f"""
            SELECT descriptor
            FROM {table}
            WHERE {table} MATCH ?
            ORDER BY (json_extract(descriptor, '$.name') = ?) DESC,
                     bm25({table}, 0, 0, 5, 3, 1),
                     json_extract(descriptor, '$.name')
            LIMIT ?
            """,
            (" OR ".join(f'"{term}"' for term in terms), query.strip(), limit),
        )
        return tuple(SkillDescriptor.model_validate_json(row[0]) for row in rows)


class SkillSearchIndex:
    """Cache immutable documents by identity, replacing stale entries when requested."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self._ranker = ScopedSkillRanker()
        self._keys: dict[str, tuple[int, str]] = {}

    def search(
        self, query: str, documents: dict[str, Callable[[], tuple[SkillDescriptor, bytes]]],
        limit: int, *, replace: bool = False, refresh_names: frozenset[str] = frozenset(),
    ) -> tuple[SkillDescriptor, ...]:
        if not has_search_terms(query):
            return ()
        with self._lock:
            if self._db is None:
                if not documents:
                    return ()
                db = sqlite3.connect(":memory:", check_same_thread=False)
                try:
                    create_index(db)
                except BaseException:
                    db.close()
                    raise
                self._db = db
            db = self._db
            removed = [
                key for key, (_, name) in self._keys.items()
                if (replace or name in refresh_names) and key not in documents
            ] if replace or refresh_names else ()
            inserted = {}
            with db:
                db.executemany(
                    "DELETE FROM skill_search_fts WHERE rowid = ?",
                    ((self._keys[key][0],) for key in removed),
                )
                for key in documents.keys() - self._keys.keys():
                    descriptor, body = documents[key]()
                    put_document(db, key, descriptor, body)
                    rowid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    inserted[key] = (rowid, descriptor.name)
            for key in removed:
                del self._keys[key]
            self._keys.update(inserted)
            return self._ranker.rank(
                db, query, documents, limit, all_indexed=len(documents) == len(self._keys)
            )

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
                self._keys.clear()
                self._ranker = ScopedSkillRanker()


def merge_skill_matches(query, base, overlay, limit):
    """Merge independent ranked sources without comparing their BM25 scores."""
    combined = sorted(
        ((position, item) for group in (base, overlay) for position, item in enumerate(group)),
        key=lambda match: (match[1].name != query.strip(), match[0], match[1].name),
    )
    return tuple(item for _, item in combined[:limit])
