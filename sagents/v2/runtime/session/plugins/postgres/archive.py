"""PostgreSQL archive implementing the complete shared SQL archive protocol."""

from .._shared.archive import SqlSessionArchive
from .state import _PostgresSessionState


class PostgresSessionArchive(SqlSessionArchive, _PostgresSessionState):
    def _archive_attachment_sql(self):
        return f"""INSERT INTO {self._table("attachments")} (session_id, artifact_id, payload)
            VALUES (%s, %s, %s) ON CONFLICT (session_id, artifact_id) DO NOTHING"""

    @staticmethod
    def _archive_attachment_params(sid, artifact_id, content):
        return sid, artifact_id, content

    def _archive_locations_sql(self):
        return f"""INSERT INTO {self._table("locations")} (kind, identity, session_id)
            VALUES (%s, %s, %s) ON CONFLICT (kind, identity)
            DO UPDATE SET session_id = EXCLUDED.session_id"""

    def _archive_starts_sql(self):
        return f"""INSERT INTO {self._table("start_idempotency")}
            (tenant_id, principal_id, idempotency_key, session_id, run_id, request_digest)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, principal_id, idempotency_key) DO UPDATE SET
            session_id = EXCLUDED.session_id, run_id = EXCLUDED.run_id,
            request_digest = EXCLUDED.request_digest"""
