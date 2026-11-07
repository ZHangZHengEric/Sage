"""MySQL dialect for the shared revision-bounded SQL archive."""
from .._shared.archive import SqlSessionArchive
from .state import _MysqlSessionState


class MysqlSessionArchive(SqlSessionArchive, _MysqlSessionState):
    def _archive_attachment_sql(self):
        return f"INSERT IGNORE INTO {self._table('attachments')} (session_id, artifact_id, payload) VALUES (%s, %s, UNHEX(%s))"

    @staticmethod
    def _archive_attachment_params(sid, artifact_id, content):
        return sid, artifact_id, content.hex()

    def _archive_locations_sql(self):
        return f"INSERT INTO {self._table('locations')} (kind, identity, session_id) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE session_id = VALUES(session_id)"

    def _archive_starts_sql(self):
        return f"INSERT INTO {self._table('start_idempotency')} (tenant_id, principal_id, idempotency_key, session_id, run_id, request_digest) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE session_id = VALUES(session_id), run_id = VALUES(run_id), request_digest = VALUES(request_digest)"
