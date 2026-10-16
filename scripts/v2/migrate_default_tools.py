"""Materialize legacy catalog tool defaults before upgrading Server v2.

Stop all Server writers first. Inspect with no arguments, then apply with
--writers-stopped --backup /secure/default-tools-before.json. The exclusive
backup contains original Package references and configuration. This is an
operator-run data migration, never a request-time configuration fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import select

from app.v2.server.catalog.orm import AgentRow
from app.v2.server.catalog.packages import package_owner
from app.v2.server.catalog.repository import _agent_record
from app.v2.server.config.settings import ServerSettings
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.packages.orm import ManagedRecordRow
from app.v2.server.packages.repository import DatabasePackageStore
from app.v2.server.runtime.official import default_agent_tools
from sagents.v2.agent.management import AgentPackageBundle


async def migrate(database, *, backup: Path | None = None):
    store = DatabasePackageStore(database)
    async with database.transaction() as session:
        query = select(AgentRow).order_by(AgentRow.id)
        if backup is not None:
            query = query.with_for_update()
        rows = list((await session.scalars(query)).all())
        candidates = []
        for row in rows:
            bundle = None
            if row.package_ref:
                saved = await session.scalar(select(ManagedRecordRow).where(
                    ManagedRecordRow.owner == package_owner(row.owner_user_id),
                    ManagedRecordRow.kind == "bundle", ManagedRecordRow.ref == row.package_ref))
                if saved is None:
                    raise ValueError(f"Missing Package for {row.id}; migration aborted")
                bundle = AgentPackageBundle.model_validate(saved.payload)
                if bundle.content_hash != row.package_ref:
                    raise ValueError(f"Package hash mismatch for {row.id}; migration aborted")
            record = _agent_record(row, [], package=bundle)
            if not record.tools:
                candidates.append((row, record))
        if backup is None:
            return {"candidates": len(candidates), "applied": False}
        document = {"migration": "explicit-catalog-tools-v1", "agents": [
            {"owner_user_id": row.owner_user_id, "agent_id": row.id,
             "package_ref": row.package_ref, "tools": row.tools,
             "record": record.model_dump(mode="json")}
            for row, record in candidates
        ]}
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(document, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        for row, record in candidates:
            updated = record.with_configuration(tools=default_agent_tools())
            row.package_ref = await store.save_in_transaction(session, package_owner(row.owner_user_id), updated.package)
            row.tools = list(updated.tools)
        return {"candidates": len(candidates), "applied": True, "backup": str(backup)}


async def main(args):
    if args.backup and not args.writers_stopped:
        raise ValueError("Stop Server writers and pass --writers-stopped before applying")
    settings = ServerSettings.from_env()
    database = Database(DatabaseSettings(url=settings.database_url()))
    await database.start()
    try:
        print(json.dumps(await migrate(database, backup=args.backup)))
    finally:
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--writers-stopped", action="store_true")
    asyncio.run(main(parser.parse_args()))
