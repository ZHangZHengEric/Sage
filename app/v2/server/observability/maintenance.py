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


async def migrate_legacy(database, sink, *, limit=10):
    async with database.session() as db:
        identity = and_(*(models.c[n] == expiry.c[n] for n in MODEL_KEY))
        keys = (await db.execute(select(*(models.c[n] for n in MODEL_KEY)).outerjoin(
            expiry, identity,
        ).where(expiry.c.request_id.is_(None)).limit(limit))).all()
        mysql = db.get_bind().dialect.name == "mysql"
    prepared = []
    for key in keys:
        async with database.session() as db:
            original = await db.scalar(select(models.c.payload).where(
                *(models.c[n] == key[i] for i, n in enumerate(MODEL_KEY)),
            ))
        if original is None:
            continue
        record = json.loads(original)
        compact = await asyncio.to_thread(sink.storage.pack, key, record)
        restored = await asyncio.to_thread(sink.storage.unpack, key, compact)
        if restored != record:
            raise ValueError("Migrated diagnostic evidence differs from the original")
        encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        observed = timestamp(record.get("completed_at")) or timestamp(record.get("started_at")) or time.time()
        days = 3 if record.get("status") == "completed" else 7
        token = sha256(original.encode()).hexdigest() if mysql else original
        prepared.append((tuple(key), encoded, token, observed, days))

    async def write(db):
        migrated = 0
        version = models.c.payload
        if mysql:
            version = func.sha2(cast(version, CHAR(charset="utf8mb4")), 256)
        # Commit small references together. Bodies were durably written and
        # verified first, and the CAS still protects every concurrent change.
        for key, encoded, token, observed, days in prepared:
            changed = await db.execute(update(models).where(
                *(models.c[n] == key[i] for i, n in enumerate(MODEL_KEY)), version == token,
            ).values(payload=encoded))
            if changed.rowcount:
                await upsert(db, expiry, [{
                    **_model_scope(key), "expires_at": observed + days * 86400,
                    "summary_expires_at": observed + 30 * 86400,
                }], key=MODEL_KEY)
                migrated += 1
        return migrated

    return await database.run_transaction(write) if prepared else 0


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
