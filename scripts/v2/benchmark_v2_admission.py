"""Compare full and scoped catalog reads on the same temporary SQLite data.

Run from the repository root:
    python -m scripts.v2.benchmark_v2_admission --agents 100 --samples 7
This measures catalog reads, not production cold-start or full chat latency.
"""

import argparse
import asyncio
import json
import statistics
import tempfile
from time import perf_counter

from sqlalchemy import event

from app.v2.server.catalog.records import AgentRecord
from app.v2.server.catalog.repository import DatabaseCatalogStore
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.identity.orm import UserRow


async def benchmark(agent_count, sample_count):
    with tempfile.TemporaryDirectory() as root:
        database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{root}/benchmark.db"))
        await database.start()
        try:
            await create_host_schema(database)
            store = DatabaseCatalogStore(database)
            async with database.transaction() as session:
                session.add(UserRow(user_id="benchmark", username="benchmark", password_hash="test", role="user"))
                await session.flush()
                await store._catalog(session, "benchmark")
                for index in range(agent_count):
                    record = AgentRecord(id=f"agent_{index}", name=f"Agent {index}",
                        instructions="business context " * 700, tools=["file_read"])
                    session.add(await store._new_agent_row(session, "benchmark", record))
            for name, read in (("full", lambda: store.get("benchmark")),
                               ("run", lambda: store.get_for_run("benchmark", "agent_0"))):
                samples, statements = [], []
                def capture(connection, cursor, sql, params, context, many):
                    statements.append(sql)
                event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
                try:
                    for _ in range(sample_count):
                        statements.clear()
                        started = perf_counter()
                        catalog = await read()
                        samples.append((perf_counter() - started) * 1000)
                finally:
                    event.remove(database._engine.sync_engine, "before_cursor_execute", capture)
                print(json.dumps({"mode": name, "agents_loaded": len(catalog.agents),
                    "queries": len(statements), "median_ms": round(statistics.median(samples), 3),
                    "samples_ms": [round(value, 3) for value in samples]}))
        finally:
            await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=100)
    parser.add_argument("--samples", type=int, default=7)
    args = parser.parse_args()
    if min(args.agents, args.samples) < 1:
        parser.error("agents and samples must be positive")
    asyncio.run(benchmark(args.agents, args.samples))
