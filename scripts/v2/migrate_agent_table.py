"""Back up the selected database and migrate Agent identities. Stop writers first.

python -m scripts.v2.migrate_agent_table --env app/v2/server/.env --backup /secure/path.json
"""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.v2.server.database.migrations.agents import prepare, migrate, finalize


async def main(args):
    url = make_url(dotenv_values(args.env)['SAGE_SERVER_MYSQL_URL'])
    if url.drivername == 'mysql':
        url = url.set(drivername='mysql+aiomysql')
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            def snapshot(conn):
                return {name: [dict(row) for row in conn.execute(select(
                    Table(name, MetaData(), autoload_with=conn))).mappings()]
                    for name in inspect(conn).get_table_names()}
            data = await connection.run_sync(snapshot)
            document = dict(database=url.database, created_at=datetime.now(timezone.utc).isoformat(), tables=data)
            fd = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(document, stream, ensure_ascii=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
        async with engine.begin() as connection:
            needed = await connection.run_sync(prepare)
        if needed:
            async with engine.begin() as connection:
                result = await connection.run_sync(migrate)
            async with engine.begin() as connection:
                await connection.run_sync(finalize)
            print(json.dumps(result))
        else:
            print('Agent table migration already complete')
        print('Backup:', Path(args.backup).resolve())
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', required=True)
    parser.add_argument('--backup', required=True)
    asyncio.run(main(parser.parse_args()))
