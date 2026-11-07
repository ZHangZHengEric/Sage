"""Transactional PostgreSQL schema bootstrap, serialized across starters."""


async def bootstrap(store, connection):
    table = store._table
    # PostgreSQL DDL is transactional. The xact lock covers inspection and DDL.
    # https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_database() || ':' || current_schema() || ':' || %s, 0))",
        (store.table_prefix,),
    )
    statements = {
        "sessions": f"""CREATE TABLE IF NOT EXISTS {table("sessions")} (
            session_id VARCHAR(128) PRIMARY KEY,
            parent_session_id VARCHAR(128), revision BIGINT NOT NULL,
            last_sequence BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, compact_state JSONB NOT NULL)""",
        "session_mutations": f"""CREATE TABLE IF NOT EXISTS {table("session_mutations")} (
            session_id VARCHAR(128) NOT NULL REFERENCES {table("sessions")} ON DELETE CASCADE,
            revision BIGINT NOT NULL, mutation JSONB NOT NULL,
            PRIMARY KEY (session_id, revision))""",
        "run_events": f"""CREATE TABLE IF NOT EXISTS {table("run_events")} (
            session_id VARCHAR(128) NOT NULL REFERENCES {table("sessions")} ON DELETE CASCADE,
            run_id VARCHAR(128) NOT NULL, run_sequence BIGINT NOT NULL,
            session_sequence BIGINT, event JSONB NOT NULL,
            PRIMARY KEY (run_id, run_sequence))""",
        "locations": f"""CREATE TABLE IF NOT EXISTS {table("locations")} (
            kind VARCHAR(64) NOT NULL, identity VARCHAR(128) NOT NULL,
            session_id VARCHAR(128) NOT NULL REFERENCES {table("sessions")} ON DELETE CASCADE,
            PRIMARY KEY (kind, identity))""",
        "start_idempotency": f"""CREATE TABLE IF NOT EXISTS {table("start_idempotency")} (
            tenant_id VARCHAR(128) NOT NULL DEFAULT '', principal_id VARCHAR(128) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            session_id VARCHAR(128) NOT NULL REFERENCES {table("sessions")} ON DELETE CASCADE,
            run_id VARCHAR(128) NOT NULL, request_digest VARCHAR(128) NOT NULL,
            PRIMARY KEY (tenant_id, principal_id, idempotency_key))""",
        "derived_state": f"""CREATE TABLE IF NOT EXISTS {table("derived_state")} (
            session_id VARCHAR(128) NOT NULL REFERENCES {table("sessions")} ON DELETE CASCADE,
            namespace VARCHAR(128) NOT NULL, "key" VARCHAR(128) NOT NULL,
            value JSONB NOT NULL, PRIMARY KEY (session_id, namespace, "key"))""",
        "attachments": f"""CREATE TABLE IF NOT EXISTS {table("attachments")} (
            session_id VARCHAR(128) NOT NULL REFERENCES {table("sessions")} ON DELETE CASCADE,
            artifact_id VARCHAR(128) NOT NULL, payload BYTEA NOT NULL,
            PRIMARY KEY (session_id, artifact_id))""",
    }
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        )
        existing = {row[0] for row in await cursor.fetchall()}
        created = []
        for name, statement in statements.items():
            if store._physical_table(name) not in existing:
                await cursor.execute(statement)
                created.append(store._physical_table(name))
        for name, suffix, columns in (
            ("sessions", "parent_idx", "parent_session_id"),
            ("run_events", "session_seq_idx", "session_id, session_sequence"),
            ("locations", "session_idx", "session_id"),
        ):
            index = store._table(name + "_" + suffix)
            await cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {index} ON {table(name)} ({columns})"
            )
    await connection.commit()
    return tuple(created)
