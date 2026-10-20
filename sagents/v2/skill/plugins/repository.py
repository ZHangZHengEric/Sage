"""Transactional Skill repositories with immutable versions and durable Run pins.

Repository roots are trusted host configuration. Hosts must use separate roots
for separate tenants; publishing is deliberately not exposed as an Agent tool.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.errors import ErrorCategory
from sagents.v2.skill.bundles import files_digest, skill_error
from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor


class SqliteSkillRepository:
    """Metadata and complete version packages committed in one transaction.

    The first catalog access pins the complete visible catalog for a Run. Later
    publishes affect new Runs only. Pins and old versions survive process restart.
    """

    plugin_id = "sage.skill.repository.sqlite"
    name = "Versioned SQLite Skill repository"
    description = (
        "Atomic publishing, immutable packages and durable per-Run version pins."
    )

    def __init__(
        self, path: str | Path, *, max_files=2000, max_total_bytes=64 * 1024**2
    ):
        self.path = str(path)
        if self.path != ":memory:":
            self.path = str(Path(path).expanduser().resolve())
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS skill_versions (
                name TEXT NOT NULL, version TEXT NOT NULL,
                descriptor TEXT NOT NULL, content_hash TEXT NOT NULL,
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, UNIQUE(name, version)
            );
            CREATE TABLE IF NOT EXISTS skill_version_files (
                name TEXT NOT NULL, version TEXT NOT NULL, path TEXT NOT NULL,
                content BLOB NOT NULL, PRIMARY KEY(name, version, path)
            );
            CREATE TABLE IF NOT EXISTS skill_heads (name TEXT PRIMARY KEY, version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS skill_run_pins (run_id TEXT PRIMARY KEY, catalog TEXT NOT NULL);
        """)

    async def publish(
        self, bundle: SkillBundle, *, expected_version: str | None = None
    ) -> SkillDescriptor:
        # Copy mutable payloads before leaving the caller's task.
        bundle = SkillBundle.model_validate(bundle.model_dump())
        if (
            len(bundle.files) > self.max_files
            or sum(map(len, bundle.files.values())) > self.max_total_bytes
        ):
            raise skill_error(
                "skill.bundle_too_large",
                "Skill exceeds repository limits",
                ErrorCategory.VALIDATION,
            )
        bundle.files["SKILL.md"].decode("utf-8")
        return await bounded_to_thread(
            "skill-io", lambda: self._publish(bundle, expected_version)
        )

    def _publish(self, bundle, expected_version):
        content_hash = files_digest(bundle.files)
        identity = json.dumps(
            {
                "name": bundle.descriptor.name,
                "description": bundle.descriptor.description,
                "content_hash": content_hash,
                "metadata": bundle.descriptor.metadata,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        version = "sha256:" + hashlib.sha256(identity.encode()).hexdigest()
        descriptor = bundle.descriptor.model_copy(
            update={
                "version": version,
                "source_id": "repository",
            }
        )
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                current = self._db.execute(
                    "SELECT version FROM skill_heads WHERE name=?", (descriptor.name,)
                ).fetchone()
                if (
                    expected_version is not None
                    and (current[0] if current else None) != expected_version
                ):
                    raise skill_error(
                        "skill.publish_conflict",
                        "Skill changed since the editor's base version",
                    )
                inserted = self._db.execute(
                    "INSERT OR IGNORE INTO skill_versions(name,version,descriptor,content_hash) VALUES(?,?,?,?)",
                    (
                        descriptor.name,
                        version,
                        descriptor.model_dump_json(),
                        content_hash,
                    ),
                )
                if inserted.rowcount:
                    self._db.executemany(
                        "INSERT INTO skill_version_files(name,version,path,content) VALUES(?,?,?,?)",
                        (
                            (descriptor.name, version, path, content)
                            for path, content in bundle.files.items()
                        ),
                    )
                self._db.execute(
                    "INSERT OR REPLACE INTO skill_heads(name,version) VALUES(?,?)",
                    (descriptor.name, version),
                )
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        return descriptor

    def _pinned_catalog(self, run_id):
        # Caller holds the instance lock. BEGIN IMMEDIATE serializes first-pin
        # creation and publication across independent repository processes too.
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT catalog FROM skill_run_pins WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                values = self._db.execute("""
                    SELECT v.descriptor FROM skill_heads h JOIN skill_versions v
                    ON h.name=v.name AND h.version=v.version ORDER BY h.name
                """).fetchall()
                catalog = [json.loads(value[0]) for value in values]
                self._db.execute(
                    "INSERT INTO skill_run_pins(run_id,catalog) VALUES(?,?)",
                    (run_id, json.dumps(catalog)),
                )
            else:
                catalog = json.loads(row[0])
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return tuple(SkillDescriptor.model_validate(value) for value in catalog)

    async def list_skills(self, *, run_id):
        def read():
            with self._lock:
                return self._pinned_catalog(run_id)

        return await bounded_to_thread("skill-io", read)

    async def get_skill(self, name, *, run_id):
        values = await self.list_skills(run_id=run_id)
        for descriptor in values:
            if descriptor.name == name:
                return descriptor
        raise skill_error(
            "skill.not_found",
            f"Skill {name!r} is not in this Run's catalog",
            ErrorCategory.VALIDATION,
        )

    async def fetch(self, name, *, run_id):
        descriptor = await self.get_skill(name, run_id=run_id)
        return await self.fetch_version(name, descriptor.version)

    async def fetch_latest(self, name, *, run_id):
        # Keep the Run's admitted-name boundary while deliberately selecting
        # current manager bytes for the auto-sync workspace policy.
        await self.get_skill(name, run_id=run_id)

        def read():
            with self._lock:
                row = self._db.execute(
                    "SELECT version FROM skill_heads WHERE name=?", (name,)
                ).fetchone()
            if row is None:
                raise skill_error(
                    "skill.not_found",
                    f"Skill {name!r} is unavailable",
                    ErrorCategory.VALIDATION,
                )
            return row[0]

        version = await bounded_to_thread("skill-io", read)
        return await self.fetch_version(name, version)

    async def fetch_version(self, name: str, version: str) -> SkillBundle:
        def read():
            with self._lock:
                row = self._db.execute(
                    "SELECT descriptor,content_hash FROM skill_versions WHERE name=? AND version=?",
                    (name, version),
                ).fetchone()
                files = dict(
                    self._db.execute(
                        "SELECT path,content FROM skill_version_files WHERE name=? AND version=? ORDER BY path",
                        (name, version),
                    ).fetchall()
                )
            if row is None:
                raise skill_error(
                    "skill.not_found",
                    f"Unknown Skill version {name!r}/{version!r}",
                    ErrorCategory.VALIDATION,
                )
            if files_digest(files) != row[1]:
                raise skill_error(
                    "skill.artifact_changed",
                    "Stored Skill package no longer matches its hash",
                )
            return SkillBundle(
                descriptor=SkillDescriptor.model_validate_json(row[0]),
                files=files,
                content_hash=row[1],
            )

        return await bounded_to_thread("skill-io", read)

    async def list_versions(self, name):
        def read():
            with self._lock:
                rows = self._db.execute(
                    "SELECT descriptor FROM skill_versions WHERE name=? ORDER BY sequence",
                    (name,),
                ).fetchall()
            return tuple(SkillDescriptor.model_validate_json(row[0]) for row in rows)

        return await bounded_to_thread("skill-io", read)

    async def close(self):
        def close():
            with self._lock:
                self._db.close()

        await bounded_to_thread("skill-io", close)


class MemorySkillRepository(SqliteSkillRepository):
    """Transactional repository whose versions and Run pins live in memory only."""

    plugin_id = "sage.skill.repository.memory"
    name = "In-memory Skill repository"
    description = "Versioned publishing and Run pins for temporary applications."

    def __init__(self, **kwargs):
        super().__init__(":memory:", **kwargs)
