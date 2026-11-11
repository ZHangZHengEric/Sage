"""Provision libSQL memory and import former Server SQLite stores."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
from itertools import batched
import json
import os
from pathlib import Path
import sqlite3

from dotenv import load_dotenv
from sqlalchemy import select

from app.v2.server.config.settings import ServerSettings
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.database.upsert import upsert
from app.v2.server.memory.libsql import LibSQLMemoryProvider, LibSQLSessionMemoryProvider, prepare_memory_schema
from app.v2.server.memory.libsql_client import LibSQLClient
from app.v2.server.observability.orm import dropped, events, logs, models, timings
from app.v2.server.self_configuration.repository import SelfConfigurationRecord, record_key
from sagents.v2.memory.contracts import MemoryRecord
from sagents.v2.session_memory.contracts import SessionMemoryRecord


async def _copy_row(db, table, values):
    keys = tuple(column.name for column in table.primary_key)
    await upsert(db, table, values, key=keys)
    stored = (await db.execute(select(table).filter_by(
        **{key: values[key] for key in keys}
    ))).mappings().one()
    if dict(stored) != values:
        raise ValueError(f"Conflicting row already exists in {table.name}")


async def import_self_configuration(database, path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("BEGIN")
        async with database.transaction() as db:
            table = SelfConfigurationRecord.__table__
            count = 0
            for name, keys in (("defaults", ()), ("runs", ("run",))):
                columns = ", ".join(("owner", *keys, "data"))
                kind = "defaults" if name == "defaults" else "run"
                for owner, *parts, data in source.execute(f"SELECT {columns} FROM {name}"):
                    await _copy_row(db, table, {
                        "key": record_key(owner, kind, *parts), "payload": json.loads(data),
                    })
                    count += 1
            for owner, run, operation, fingerprint, result in source.execute(
                "SELECT owner, run, operation, fingerprint, result FROM operations"
            ):
                await _copy_row(db, table, {
                    "key": record_key(owner, "operation", run, operation),
                    "payload": {"fingerprint": fingerprint, "result": json.loads(result)},
                })
                count += 1
    return count


async def import_diagnostics(database, path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        async with database.transaction() as db:
            count = 0
            for name, table in (
                ("models", models), ("logs", logs), ("dropped", dropped),
                ("performance_events", events), ("performance_models", timings),
            ):
                columns = ", ".join(table.c.keys())
                for record in source.execute(f"SELECT {columns} FROM {name}"):
                    values = dict(record)
                    if table is logs:
                        # Preserve legacy order and leave positive IDs to the database sequence.
                        values["id"] -= 2**63
                    await _copy_row(db, table, values)
                    count += 1
    return count


async def import_session_memory(database, path: Path) -> int:
    provider = LibSQLSessionMemoryProvider(database)
    count = 0
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("BEGIN")
        rows = source.execute(
            "SELECT payload_json FROM session_memory_records ORDER BY session_id, record_id",
        )
        for batch in batched(rows, 250):
            await provider.import_records(
                tuple(SessionMemoryRecord.model_validate_json(payload) for (payload,) in batch),
            )
            count += len(batch)
    return count


async def import_memory(database, path: Path) -> int:
    provider = LibSQLMemoryProvider(database)
    count = 0
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("BEGIN")
        rows = source.execute("SELECT payload_json FROM memory_records ORDER BY scope_key, memory_id")
        for batch in batched(rows, 250):
            await provider.import_records(
                tuple(MemoryRecord.model_validate_json(payload) for (payload,) in batch),
            )
            count += len(batch)
    return count


async def _run(args):
    load_dotenv(Path(__file__).parents[1] / ".env", override=False)
    if args.init_libsql or args.memory or args.session_memory:
        url = os.environ.get("SAGE_SERVER_LIBSQL_URL", "").strip()
        if not url:
            raise ValueError("SAGE_SERVER_LIBSQL_URL is required for libSQL provisioning and import")
        token = os.environ.get("SAGE_SERVER_LIBSQL_AUTH_TOKEN", "").strip()
        async with LibSQLClient(url, token) as remote:
            await prepare_memory_schema(remote)
            if args.memory:
                count = await import_memory(remote, args.memory)
                print(f"Long-term memory records verified in libSQL: {count}")
            if args.session_memory:
                count = await import_session_memory(remote, args.session_memory)
                print(f"Session memory records verified in libSQL: {count}")
    if args.self_configuration or args.diagnostics:
        settings = ServerSettings.from_env()
        database = Database(DatabaseSettings(url=settings.database_url()))
        await database.start()
        try:
            await create_host_schema(database)
            if args.self_configuration:
                count = await import_self_configuration(database, args.self_configuration)
                print(f"Self-configuration rows verified in SQL: {count}")
            if args.diagnostics:
                count = await import_diagnostics(database, args.diagnostics)
                print(f"Diagnostic rows verified in SQL: {count}")
        finally:
            await database.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-configuration", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--session-memory", type=Path)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--init-libsql", action="store_true")
    args = parser.parse_args()
    if not (args.self_configuration or args.diagnostics or args.session_memory or args.memory or args.init_libsql):
        parser.error("provide at least one source file or --init-libsql")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
