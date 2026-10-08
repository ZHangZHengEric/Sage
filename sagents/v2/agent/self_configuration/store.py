"""Atomic, single-host capability revisions and idempotent operation receipts."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path

from sagents.v2._concurrency import bounded_to_thread


class SqliteSelfConfigurationStore:
    """Keep Agent defaults separate from frozen Run revisions. No credentials."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS defaults (owner TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS runs (owner TEXT, run TEXT, data TEXT NOT NULL, PRIMARY KEY(owner, run))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS operations (owner TEXT, run TEXT, operation TEXT, fingerprint TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(owner, run, operation))"
        )
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def read(self, owner: str, run_id: str, *, create: bool = True) -> dict:
        def read():
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT data FROM runs WHERE owner=? AND run=?", (owner, run_id)
                ).fetchone()
                if row is None:
                    if not create:
                        raise ValueError("saved Run capability revision is missing")
                    row = db.execute(
                        "SELECT data FROM defaults WHERE owner=?", (owner,)
                    ).fetchone()
                    data = (
                        row[0]
                        if row
                        else json.dumps(
                            {"revision": 0, "skills": {}, "mcp_servers": {}}
                        )
                    )
                    db.execute(
                        "INSERT INTO runs VALUES (?, ?, ?)", (owner, run_id, data)
                    )
                else:
                    data = row[0]
                return json.loads(data)

        return await bounded_to_thread("memory-io", read)

    async def receipt(self, owner: str, run_id: str, operation: str):
        def read():
            with self._connect() as db:
                row = db.execute(
                    "SELECT fingerprint, result FROM operations WHERE owner=? AND run=? AND operation=?",
                    (owner, run_id, operation),
                ).fetchone()
                return (row[0], json.loads(row[1])) if row else None

        return await bounded_to_thread("memory-io", read)

    async def commit(
        self,
        owner: str,
        run_id: str,
        operation: str,
        fingerprint: str,
        expected_revision: int,
        skills: dict,
        servers: dict,
        *,
        system_prompt: str | None = None,
    ) -> dict:
        def commit():
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                receipt = db.execute(
                    "SELECT fingerprint, result FROM operations WHERE owner=? AND run=? AND operation=?",
                    (owner, run_id, operation),
                ).fetchone()
                if receipt:
                    if receipt[0] != fingerprint:
                        raise ValueError(
                            "self configuration operation conflicts with an earlier request"
                        )
                    return json.loads(receipt[1])
                row = db.execute(
                    "SELECT data FROM runs WHERE owner=? AND run=?", (owner, run_id)
                ).fetchone()
                current = json.loads(row[0])
                if current["revision"] != expected_revision:
                    raise ValueError(
                        "self configuration revision changed; read and submit again"
                    )
                current["skills"].update(skills)
                current["mcp_servers"].update(servers)
                current["revision"] += 1
                defaults = db.execute(
                    "SELECT data FROM defaults WHERE owner=?", (owner,)
                ).fetchone()
                future = (
                    json.loads(defaults[0])
                    if defaults
                    else {"revision": 0, "skills": {}, "mcp_servers": {}}
                )
                # Concurrent Runs may add disjoint capabilities, never erase them.
                for key, additions in (("skills", skills), ("mcp_servers", servers)):
                    for name, value in additions.items():
                        if name in future[key] and future[key][name] != value:
                            raise ValueError(
                                f"capability {name!r} already has a different saved definition"
                            )
                    future[key].update(additions)
                if system_prompt is not None:
                    # A stale Run must not silently replace a newer Run's prompt.
                    if (
                        future.get("system_prompt", "")
                        != current.get("system_prompt", "")
                        and future.get("system_prompt", "") != system_prompt
                    ):
                        raise ValueError(
                            "Agent instructions changed in another Run; start a fresh Run before replacing them"
                        )
                    current["system_prompt"] = system_prompt
                    future["system_prompt"] = system_prompt
                future["revision"] += 1
                result = {
                    "revision": current["revision"],
                    "added_skills": sorted(skills),
                    "added_mcp_servers": sorted(servers),
                    "effective": "next_model_step",
                    "persistent": True,
                    "system_prompt_updated": system_prompt is not None,
                }
                encoded = json.dumps(current)
                db.execute(
                    "UPDATE runs SET data=? WHERE owner=? AND run=?",
                    (encoded, owner, run_id),
                )
                db.execute(
                    "INSERT OR REPLACE INTO defaults VALUES (?, ?)",
                    (owner, json.dumps(future)),
                )
                db.execute(
                    "INSERT INTO operations VALUES (?, ?, ?, ?, ?)",
                    (owner, run_id, operation, fingerprint, json.dumps(result)),
                )
                return result

        return await bounded_to_thread("memory-io", commit)
