"""Revision-bounded SQL archival with backend-owned SQL expressions."""

import asyncio
from .aggregate import _json, _decode_json, _LOCATION_KINDS, _principal_lookup_key

NAMESPACE = "sage.workspace.lifecycle.v1"


class SqlSessionArchive:
    batch_rows = 128
    batch_bytes = 256 * 1024

    async def revision(self, sid):
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT revision FROM {self._table('sessions')} WHERE session_id = %s",
                    (sid,),
                )
                row = await cursor.fetchone()
        return None if row is None else int(row[0])

    async def revisions(self, session_ids):
        """Read archive watermarks in bounded pages before serial archival writes."""
        ids = tuple(dict.fromkeys(session_ids))
        result = {}
        if not ids:
            return result
        async with self._reader_connection() as connection:
            async with connection.cursor() as cursor:
                for start in range(0, len(ids), self.batch_rows):
                    batch = ids[start : start + self.batch_rows]
                    placeholders = ", ".join(["%s"] * len(batch))
                    await cursor.execute(
                        f"SELECT session_id, revision FROM {self._table('sessions')} "
                        f"WHERE session_id IN ({placeholders})",
                        batch,
                    )
                    result.update(
                        (sid, int(revision))
                        for sid, revision in await cursor.fetchall()
                    )
        return result

    async def archive_attachments(self, sid, attachments):
        # Attachments are immutable. Persist each before publishing revisions
        # which reference it, without one transaction spanning all blobs.
        for artifact_id, content in attachments.items():
            async with self._writer_connection() as connection:
                try:
                    async with connection.cursor() as cursor:
                        await cursor.execute(
                            self._archive_attachment_sql(),
                            self._archive_attachment_params(sid, artifact_id, content),
                        )
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise

    async def _insert_batches(self, cursor, statement, rows):
        batch, size = [], 0
        for row in rows:
            # Include escaping and SQL framing; one indivisible record may exceed
            # the byte target, but must not pull the following records into it.
            row_size = sum(len(str(value).encode("utf-8")) * 2 + 32 for value in row)
            if batch and (
                len(batch) >= self.batch_rows or size + row_size > self.batch_bytes
            ):
                await cursor.executemany(statement, batch)
                batch, size = [], 0
            batch.append(row)
            size += row_size
        if batch:
            await cursor.executemany(statement, batch)

    async def archive_batch(self, sid, mutations):
        """Commit contiguous revisions and their events together; retries skip committed prefixes."""

        def prepare():
            result = []
            for revision, encoded in mutations:
                delta = _decode_json(encoded)
                head = delta["upserts"]["sessions"][0]
                if int(head["revision"]) != revision:
                    raise ValueError("archive mutation has an invalid revision")
                appended = delta.get("appends", {}).pop("run_events", {})
                replaced = delta.get("replacements", {}).pop("run_events", {})
                deleted = set(delta.get("map_deletes", {}).pop("run_events", ()))
                removed = deleted | replaced.keys()
                event_rows = {**appended, **replaced}
                events = [
                    (
                        sid,
                        run_id,
                        row["run_sequence"],
                        row.get("session_sequence"),
                        _json(row),
                    )
                    for run_id, rows in event_rows.items()
                    if run_id not in deleted
                    for row in rows
                ]
                result.append((revision, head, delta, _json(delta), events, removed))
            return result

        prepared = await asyncio.to_thread(prepare)
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT revision FROM {self._table('sessions')} WHERE session_id = %s FOR UPDATE",
                        (sid,),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise ValueError("Session archive base is missing")
                    current = int(row[0])
                    await cursor.execute(
                        f"SELECT value FROM {self._table('derived_state')} WHERE session_id = %s AND namespace = %s AND {self.key_column} = 'runs'",
                        (sid, NAMESPACE),
                    )
                    cached = await cursor.fetchone()
                    projection = _decode_json(cached[0]) if cached else None
                    states = (
                        dict(projection["states"])
                        if (
                            isinstance(projection, dict)
                            and projection.get("revision") == current
                            and isinstance(projection.get("states"), dict)
                        )
                        else None
                    )
                    for revision, head, delta, encoded, events, removed in prepared:
                        if revision <= current:
                            continue
                        if revision != current + 1:
                            raise ValueError("non-contiguous archive revisions")
                        for run_id in removed:
                            await cursor.execute(
                                f"DELETE FROM {self._table('run_events')} WHERE session_id = %s AND run_id = %s",
                                (sid, run_id),
                            )
                        await self._insert_batches(
                            cursor,
                            f"INSERT INTO {self._table('run_events')} (session_id, run_id, run_sequence, session_sequence, event) VALUES (%s, %s, %s, %s, CAST(%s AS {self.json_type}))",
                            events,
                        )
                        await cursor.execute(
                            f"INSERT INTO {self._table('session_mutations')} (session_id, revision, mutation) VALUES (%s, %s, CAST(%s AS {self.json_type}))",
                            (sid, revision, encoded),
                        )
                        locations = sorted(self._location_rows(sid, delta["upserts"]))
                        await self._insert_batches(
                            cursor, self._archive_locations_sql(), locations
                        )
                        for collection, kind in _LOCATION_KINDS:
                            for identity in delta["deletes"].get(collection, ()):
                                await cursor.execute(
                                    f"DELETE FROM {self._table('locations')} WHERE kind = %s AND identity = %s AND session_id = %s",
                                    (kind, str(identity[0]), sid),
                                )
                        starts = sorted(self._start_key_rows(sid, delta["upserts"]))
                        await self._insert_batches(
                            cursor, self._archive_starts_sql(), starts
                        )
                        for tenant, principal_type, principal_id, key in delta[
                            "deletes"
                        ].get("start_idempotency", ()):
                            await cursor.execute(
                                f"DELETE FROM {self._table('start_idempotency')} WHERE tenant_id = %s AND principal_id = %s AND idempotency_key = %s AND session_id = %s",
                                (
                                    tenant or "",
                                    _principal_lookup_key(
                                        principal_type or "", principal_id
                                    ),
                                    key,
                                    sid,
                                ),
                            )
                        await cursor.execute(
                            f"UPDATE {self._table('sessions')} SET parent_session_id = %s, revision = %s, last_sequence = %s, updated_at = %s WHERE session_id = %s",
                            (
                                head.get("parent_session_id"),
                                revision,
                                head["last_sequence"],
                                self._storage_datetime(head["updated_at"]),
                                sid,
                            ),
                        )
                        current = revision
                        if states is not None:
                            for run in delta.get("upserts", {}).get("runs", ()):
                                states[run["run_id"]] = run["state"]
                            for run in delta.get("patches", {}).get("runs", ()):
                                if run.get("state") is not None:
                                    states[run["run_id"]] = run["state"]
                            for identity in delta.get("deletes", {}).get("runs", ()):
                                states.pop(identity[0], None)
                    if states is not None:
                        await self._write_workspace_projection(
                            cursor, sid, current, states
                        )
                await connection.commit()
                return current
            except BaseException:
                await connection.rollback()
                raise

    async def _fetch_session(self, session_id):
        await self._ensure_ready()
        return await super()._fetch_session(session_id)

    async def _locate_session(self, kind, identity):
        await self._ensure_ready()
        return await super()._locate_session(kind, identity)

    async def _read_start_lookup(self, command, context):
        await self._ensure_ready()
        return await super()._read_start_lookup(command, context)

    async def _list_descendant_ids(self, session_id):
        await self._ensure_ready()
        return await super()._list_descendant_ids(session_id)

    async def archive_session(self, payload, attachments):
        """Publish a complete aggregate and its events in one SQL transaction.

        A locked revision comparison makes retry after an ambiguous commit safe
        and prevents an older archive from overwriting a newer Session.
        """
        await self._ensure_ready()
        head = payload["sessions"][0]
        sid, revision = head["session_id"], int(head["revision"])
        async with self._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT revision FROM {self._table('sessions')} WHERE session_id = %s FOR UPDATE",
                        (sid,),
                    )
                    previous = await cursor.fetchone()
                    if previous is not None and int(previous[0]) >= revision:
                        await connection.rollback()
                        return
                    compact = await asyncio.to_thread(
                        lambda: _json(self._compact_state(payload))
                    )
                    if previous is None:
                        await cursor.execute(
                            f"INSERT INTO {self._table('sessions')} "
                            "(session_id, parent_session_id, revision, last_sequence, created_at, updated_at, compact_state) "
                            f"VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS {self.json_type}))",
                            (
                                sid,
                                head.get("parent_session_id"),
                                revision,
                                head["last_sequence"],
                                self._storage_datetime(head["created_at"]),
                                self._storage_datetime(head["updated_at"]),
                                compact,
                            ),
                        )
                    else:
                        await cursor.execute(
                            f"UPDATE {self._table('sessions')} SET parent_session_id = %s, revision = %s, "
                            f"last_sequence = %s, updated_at = %s, compact_state = CAST(%s AS {self.json_type}) WHERE session_id = %s",
                            (
                                head.get("parent_session_id"),
                                revision,
                                head["last_sequence"],
                                self._storage_datetime(head["updated_at"]),
                                compact,
                                sid,
                            ),
                        )
                    await cursor.execute(
                        f"SELECT run_id, MAX(run_sequence) FROM {self._table('run_events')} "
                        "WHERE session_id = %s GROUP BY run_id",
                        (sid,),
                    )
                    offsets = {
                        run_id: int(sequence)
                        for run_id, sequence in await cursor.fetchall()
                    }
                    for run_id, events in payload.get("run_events", {}).items():
                        appended = [
                            event
                            for event in events
                            if event["run_sequence"] > offsets.get(run_id, 0)
                        ]
                        if appended:
                            await self._insert_batches(
                                cursor,
                                f"INSERT INTO {self._table('run_events')} "
                                "(session_id, run_id, run_sequence, session_sequence, event) "
                                f"VALUES (%s, %s, %s, %s, CAST(%s AS {self.json_type}))",
                                [
                                    (
                                        sid,
                                        run_id,
                                        event["run_sequence"],
                                        event.get("session_sequence"),
                                        _json(event),
                                    )
                                    for event in appended
                                ],
                            )
                    await cursor.execute(
                        f"DELETE FROM {self._table('session_mutations')} WHERE session_id = %s",
                        (sid,),
                    )
                    await cursor.execute(
                        f"DELETE FROM {self._table('locations')} WHERE session_id = %s",
                        (sid,),
                    )
                    locations = sorted(self._location_rows(sid, payload))
                    if locations:
                        await self._insert_batches(
                            cursor,
                            f"INSERT INTO {self._table('locations')} (kind, identity, session_id) VALUES (%s, %s, %s)",
                            locations,
                        )
                    await cursor.execute(
                        f"DELETE FROM {self._table('start_idempotency')} WHERE session_id = %s",
                        (sid,),
                    )
                    starts = sorted(self._start_key_rows(sid, payload))
                    if starts:
                        await self._insert_batches(
                            cursor,
                            f"INSERT INTO {self._table('start_idempotency')} "
                            "(tenant_id, principal_id, idempotency_key, session_id, run_id, request_digest) "
                            "VALUES (%s, %s, %s, %s, %s, %s)",
                            starts,
                        )
                    await self._write_workspace_projection(
                        cursor,
                        sid,
                        revision,
                        {
                            run["run_id"]: run["state"]
                            for run in payload.get("runs", ())
                        },
                    )
                    for artifact_id, content in attachments.items():
                        await cursor.execute(
                            self._archive_attachment_sql(),
                            self._archive_attachment_params(sid, artifact_id, content),
                        )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def delete_archived_sessions(self, session_ids):
        await self._delete_storage_locked("", frozenset(session_ids))
