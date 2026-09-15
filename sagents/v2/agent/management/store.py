"""SQLite inventory, immutable bundles and optimistic active-version pointers."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sagents.v2.agent.management.contracts import AgentPackageBundle


class AgentPackageStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS bundles (
                    owner TEXT NOT NULL, ref TEXT NOT NULL, package TEXT NOT NULL,
                    version TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(owner, ref), UNIQUE(owner, package, version));
                CREATE TABLE IF NOT EXISTS active (
                    owner TEXT NOT NULL, package TEXT NOT NULL, ref TEXT NOT NULL,
                    PRIMARY KEY(owner, package));
                CREATE TABLE IF NOT EXISTS invocations (
                    owner TEXT NOT NULL, operation TEXT NOT NULL, ref TEXT NOT NULL,
                    agent TEXT NOT NULL, request TEXT NOT NULL, handle TEXT,
                    PRIMARY KEY(owner, operation));
                CREATE TABLE IF NOT EXISTS reply_attempts (
                    owner TEXT NOT NULL, operation TEXT NOT NULL,
                    interaction TEXT NOT NULL, request TEXT NOT NULL,
                    command TEXT NOT NULL,
                    PRIMARY KEY(owner, operation, interaction, request));
                CREATE TABLE IF NOT EXISTS history_locations (
                    owner TEXT NOT NULL, ref TEXT NOT NULL, agent TEXT NOT NULL, root TEXT NOT NULL,
                    PRIMARY KEY(owner, ref, agent));
                CREATE TABLE IF NOT EXISTS terminal_statuses (
                    owner TEXT NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(owner, operation));
                CREATE INDEX IF NOT EXISTS invocation_application_lookup
                    ON invocations(owner, ref, agent, operation);
                CREATE INDEX IF NOT EXISTS invocation_session_lookup
                    ON invocations(owner, ref, agent, json_extract(handle, '$.session_id'));
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    async def call(self, fn, *args):
        # One connection per operation; SQLite serializes writers across services.
        # Settle the worker even when the caller is cancelled before returning.
        task = asyncio.create_task(asyncio.to_thread(fn, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def save(self, owner: str, bundle: AgentPackageBundle):
        return await self.call(self._save, owner, bundle)

    async def version_ref(self, owner, package, version):
        return await self.call(self._version_ref, owner, package, version)

    def _version_ref(self, owner, package, version):
        with self._connect() as db:
            row = db.execute(
                "SELECT ref FROM bundles WHERE owner=? AND package=? AND version=?",
                (owner, package, version),
            ).fetchone()
        return row["ref"] if row else None

    def _save(self, owner, bundle):
        ref = bundle.content_hash
        payload = bundle.model_dump_json()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT ref FROM bundles WHERE owner=? AND package=? AND version=?",
                (owner, bundle.manifest.metadata.id, bundle.manifest.metadata.version),
            ).fetchone()
            if old and old["ref"] != ref:
                raise ValueError("package version is immutable; choose a new version")
            db.execute(
                "INSERT OR IGNORE INTO bundles VALUES (?, ?, ?, ?, ?)",
                (
                    owner,
                    ref,
                    bundle.manifest.metadata.id,
                    bundle.manifest.metadata.version,
                    payload,
                ),
            )
        return ref

    async def get(self, owner, ref):
        return await self.call(self._get, owner, ref)

    def _get(self, owner, ref):
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM bundles WHERE owner=? AND ref=?", (owner, ref)
            ).fetchone()
        if row is None:
            raise ValueError("agent package not found in caller scope")
        return AgentPackageBundle.model_validate_json(row["payload"])

    async def list(self, owner, *, limit=50, offset=0):
        return await self.call(self._list, owner, limit, offset)

    def _list(self, owner, limit, offset):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid inventory pagination")
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT b.ref, b.package, b.version, a.ref AS active_ref, (a.ref=b.ref) AS active FROM bundles b "
                    "LEFT JOIN active a ON a.owner=b.owner AND a.package=b.package "
                    "WHERE b.owner=? ORDER BY b.package, b.version LIMIT ? OFFSET ?",
                    (owner, limit, offset),
                )
            ]

    async def activate(self, owner, ref, expected_ref):
        return await self.call(self._activate, owner, ref, expected_ref)

    def _activate(self, owner, ref, expected_ref):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            bundle = db.execute(
                "SELECT package FROM bundles WHERE owner=? AND ref=?", (owner, ref)
            ).fetchone()
            if bundle is None:
                raise ValueError("agent package not found in caller scope")
            old = db.execute(
                "SELECT ref FROM active WHERE owner=? AND package=?",
                (owner, bundle["package"]),
            ).fetchone()
            current = old["ref"] if old else None
            if current != expected_ref:
                raise ValueError(
                    "active version conflict; refresh inventory before retrying"
                )
            db.execute(
                "INSERT OR REPLACE INTO active VALUES (?, ?, ?)",
                (owner, bundle["package"], ref),
            )
        return {"ref": ref, "previous_ref": current, "package": bundle["package"]}

    async def invocation(
        self, owner, operation, ref=None, agent=None, request=None, handle=None
    ):
        return await self.call(
            self._invocation, owner, operation, ref, agent, request, handle
        )

    def _invocation(self, owner, operation, ref, agent, request, handle):
        with self._connect() as db:
            if request is not None or handle is not None:
                db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM invocations WHERE owner=? AND operation=?",
                (owner, operation),
            ).fetchone()
            if (
                old
                and request is not None
                and (old["ref"], old["agent"], old["request"]) != (ref, agent, request)
            ):
                raise ValueError("operation key reused with different invocation")
            if old is None:
                if request is None:
                    raise ValueError("invocation not found in caller scope")
                db.execute(
                    "INSERT INTO invocations VALUES (?, ?, ?, ?, ?, NULL)",
                    (owner, operation, ref, agent, request),
                )
            if handle is not None:
                db.execute(
                    "UPDATE invocations SET handle=? WHERE owner=? AND operation=?",
                    (json.dumps(handle), owner, operation),
                )
            result = dict(
                db.execute(
                    "SELECT * FROM invocations WHERE owner=? AND operation=?",
                    (owner, operation),
                ).fetchone()
            )
        result["handle"] = json.loads(result["handle"]) if result["handle"] else None
        return result

    async def reply_command(self, owner, operation, interaction, request, command=None):
        return await self.call(
            self._reply_command, owner, operation, interaction, request, command
        )

    def _reply_command(self, owner, operation, interaction, request, command):
        with self._connect() as db:
            if command is not None:
                db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT command FROM reply_attempts WHERE owner=? AND operation=? AND interaction=? AND request=?",
                (owner, operation, interaction, request),
            ).fetchone()
            if old:
                return json.loads(old["command"])
            if command is None:
                return None
            db.execute(
                "INSERT INTO reply_attempts VALUES (?, ?, ?, ?, ?)",
                (owner, operation, interaction, request, json.dumps(command)),
            )
        return command

    async def owns_session(self, owner, ref, agent, session_id):
        return await self.call(self._owns_session, owner, ref, agent, session_id)

    async def discard_stale_reply(
        self, owner, operation, interaction, request, command
    ):
        return await self.call(
            self._discard_stale_reply, owner, operation, interaction, request, command
        )

    def _discard_stale_reply(self, owner, operation, interaction, request, command):
        with self._connect() as db:
            # Compare the exact command: another retry may already have replaced it.
            db.execute(
                "DELETE FROM reply_attempts WHERE owner=? AND operation=? AND interaction=? AND request=? AND command=?",
                (owner, operation, interaction, request, json.dumps(command)),
            )

    def _owns_session(self, owner, ref, agent, session_id):
        with self._connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM invocations WHERE owner=? AND ref=? AND agent=? "
                    "AND json_extract(handle, '$.session_id')=? LIMIT 1",
                    (owner, ref, agent, session_id),
                ).fetchone()
                is not None
            )

    async def terminal_status(self, owner, operation, *, value=None):
        return await self.call(self._terminal_status, owner, operation, value)

    def _terminal_status(self, owner, operation, value):
        with self._connect() as db:
            if value is not None:
                if not value.get("terminal") or value.get("operation") != operation:
                    raise ValueError("only terminal operation results can be archived")
                # Verify the durable handle, not just a caller-provided cache key.
                db.execute("BEGIN IMMEDIATE")
                record = db.execute(
                    "SELECT ref, handle FROM invocations WHERE owner=? AND operation=?",
                    (owner, operation),
                ).fetchone()
                if record is None or record["handle"] is None:
                    raise ValueError("invocation not found in caller scope")
                handle = json.loads(record["handle"])
                if (
                    value["ref"] != record["ref"]
                    or value["run"]["run_id"] != handle["run_id"]
                ):
                    raise ValueError("terminal result does not match invocation")
                db.execute(
                    "INSERT INTO terminal_statuses VALUES (?, ?, ?) "
                    "ON CONFLICT(owner, operation) DO UPDATE SET payload=excluded.payload",
                    (owner, operation, json.dumps(value)),
                )
            row = db.execute(
                "SELECT payload FROM terminal_statuses WHERE owner=? AND operation=?",
                (owner, operation),
            ).fetchone()
            return json.loads(row["payload"]) if row else None

    async def unarchived_invocations(self, owner, ref, agent, *, after="", limit=100):
        return await self.call(
            self._unarchived_invocations, owner, ref, agent, after, limit
        )

    def _unarchived_invocations(self, owner, ref, agent, after, limit):
        if not 1 <= limit <= 100:
            raise ValueError("invalid invocation page size")
        with self._connect() as db:
            rows = db.execute(
                "SELECT i.* FROM invocations i WHERE owner=? AND ref=? AND agent=? "
                "AND operation>? AND handle IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM terminal_statuses t WHERE t.owner=i.owner AND t.operation=i.operation) "
                "ORDER BY operation LIMIT ?",
                (owner, ref, agent, after, limit),
            ).fetchall()
        return [{**dict(row), "handle": json.loads(row["handle"])} for row in rows]

    async def history_location(self, owner, ref, agent, *, root=None):
        return await self.call(self._history_location, owner, ref, agent, root)

    def _history_location(self, owner, ref, agent, root):
        with self._connect() as db:
            if root is not None:
                db.execute(
                    "INSERT INTO history_locations VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(owner, ref, agent) DO UPDATE SET root=excluded.root",
                    (owner, ref, agent, str(root)),
                )
            row = db.execute("SELECT root FROM history_locations WHERE owner=? AND ref=? AND agent=?",
                             (owner, ref, agent)).fetchone()
            return row["root"] if row else None

    async def list_invocations(self, owner, *, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError('invalid invocation pagination')
        def read():
            with self._connect() as db:
                rows = db.execute('SELECT operation, ref, agent, handle FROM invocations WHERE owner=? ORDER BY rowid DESC LIMIT ? OFFSET ?', (owner, limit, offset)).fetchall()
            return [{**dict(row), 'handle': json.loads(row['handle']) if row['handle'] else None} for row in rows]
        return await self.call(read)
