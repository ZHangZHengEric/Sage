"""Back up Agent references and idempotently migrate catalog configuration to packages.

Stop writers first. Startup also performs the same additive, ID-preserving migration.
python -m scripts.v2.migrate_agent_packages --env deploy/standalone/.env --backup /secure/agents.json
"""

import argparse
import asyncio
import json
import os

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.v2.server.catalog.repository import DatabaseCatalogStore
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema


async def main(args):
    url = make_url(dotenv_values(args.env)["SAGE_SERVER_MYSQL_URL"])
    if url.drivername == "mysql":
        url = url.set(drivername="mysql+aiomysql")
    database = Database(DatabaseSettings(url=url.render_as_string(hide_password=False)))
    await database.start()
    try:
        async with database.session() as db:
            tables = {}
            for table in ("agents", "agent_skill_selections", "threads"):
                tables[table] = [
                    dict(row)
                    for row in (
                        await db.execute(text(f"SELECT * FROM {table}"))
                    ).mappings()
                ]
        descriptor = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(tables, stream, ensure_ascii=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        await create_host_schema(database)
        await DatabaseCatalogStore(database).migrate_packages()
        print(
            json.dumps(
                {"migrated_or_verified": len(tables["agents"]), "backup": args.backup}
            )
        )
    finally:
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--backup", required=True)
    asyncio.run(main(parser.parse_args()))
