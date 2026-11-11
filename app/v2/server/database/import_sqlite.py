"""Copy the former Server self-configuration and diagnostics files into SQL."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from dotenv import load_dotenv
from sqlalchemy import select

from app.v2.server.config.settings import ServerSettings
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.database.upsert import upsert
from app.v2.server.observability.orm import dropped, events, logs, models, timings
from app.v2.server.self_configuration.repository import SelfConfigurationRecord, record_key


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


async def _run(args):
    load_dotenv(Path(__file__).parents[1] / ".env", override=False)
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
    args = parser.parse_args()
    if not (args.self_configuration or args.diagnostics):
        parser.error("provide at least one source file")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
