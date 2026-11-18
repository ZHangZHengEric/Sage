"""Migrate legacy model evidence without logging large payload rewrites."""

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import time

from sqlalchemy import and_, cast, event, func, select, update
from sqlalchemy.dialects.mysql import CHAR

from app.v2.server.config.settings import ServerSettings
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.upsert import upsert
from .diagnostics import DatabaseDiagnostics, MODEL_KEY, _model_scope
from .orm import models, expiry
from sagents.v2.runtime.observability.performance.aggregation import timestamp


async def migrate_legacy(database, sink, *, limit=100):
    migrated = 0
    for _ in range(limit):
        async with database.session() as db:
            identity = tuple(models.c[n] == expiry.c[n] for n in MODEL_KEY)
            row = (await db.execute(select(models).outerjoin(expiry, and_(*identity)).where(
                expiry.c.request_id.is_(None),
            ).limit(1))).mappings().first()
        if row is None:
            break
        key = tuple(row[n] for n in MODEL_KEY)
        original = row["payload"]
        record = json.loads(original)
        compact = await asyncio.to_thread(sink.storage.pack, key, record)
        restored = await asyncio.to_thread(sink.storage.unpack, key, compact)
        if restored != record:
            raise ValueError("Migrated diagnostic evidence differs from the original")
        encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        observed = timestamp(record.get("completed_at")) or timestamp(record.get("started_at")) or time.time()
        days = 3 if record.get("status") == "completed" else 7

        async def write(db):
            version = models.c.payload
            token = original
            if db.get_bind().dialect.name == "mysql":
                version = func.sha2(cast(version, CHAR(charset="utf8mb4")), 256)
                token = sha256(original.encode()).hexdigest()
            changed = await db.execute(update(models).where(
                *(models.c[n] == key[i] for i, n in enumerate(MODEL_KEY)), version == token,
            ).values(payload=encoded))
            if changed.rowcount:
                await upsert(db, expiry, [{
                    **_model_scope(key), "expires_at": observed + days * 86400,
                    "summary_expires_at": observed + 30 * 86400,
                }], key=MODEL_KEY)
            return bool(changed.rowcount)

        migrated += await database.run_transaction(write)
    return migrated


async def main(args):
    settings = ServerSettings.from_env()
    database = Database(DatabaseSettings(url=settings.database_url(), pool_size=1, max_overflow=0))
    await database.start()
    if args.disable_binlog:
        if database._engine.dialect.name != "mysql":
            raise ValueError("The no-binlog maintenance option requires MySQL")
        # Only this maintenance process uses this connection. Never change the
        # global binary logging configuration or application writer sessions.
        await database._engine.dispose()
        @event.listens_for(database._engine.sync_engine, "connect")
        def disable_logging(connection, _):
            cursor = connection.cursor()
            try:
                cursor.execute("SET SESSION sql_log_bin = 0")
            finally:
                cursor.close()
    sink = DatabaseDiagnostics(database, Path(args.root) if args.root else settings.data_root / "diagnostic-evidence")
    try:
        total = 0
        while True:
            count = await migrate_legacy(database, sink, limit=10)
            total += count
            print(f"Verified legacy diagnostic records migrated: {total}", flush=True)
            async with database.session() as db:
                remaining = await db.scalar(select(func.count()).select_from(models).outerjoin(
                    expiry, and_(*(models.c[n] == expiry.c[n] for n in MODEL_KEY)),
                ).where(expiry.c.request_id.is_(None)))
            if not remaining:
                break
            await asyncio.sleep(0.1)
        while await sink.prune():
            await asyncio.sleep(0.1)
    finally:
        await sink.close()
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root")
    parser.add_argument("--disable-binlog", action="store_true")
    asyncio.run(main(parser.parse_args()))
