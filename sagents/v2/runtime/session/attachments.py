"""Session-owned immutable attachments and portable session backups.

Each Session owns its attachment references and bytes. Sharing a reference
copies the snapshot into the destination Session, so deleting either owner
does not invalidate the other. Backends persist binary bytes with their own
Session transaction; only explicit portable backups encode bytes as base64.
"""

from __future__ import annotations

import base64
import hashlib
from copy import deepcopy

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.contracts import ArtifactRef


class SessionAttachmentMixin:
    async def put_attachment(
        self, session_id, *, artifact_id, media_type, content, context, metadata=None
    ):
        payload = b"".join([chunk async for chunk in content])
        reference = ArtifactRef(
            artifact_id=artifact_id,
            media_type=media_type,
            size_bytes=len(payload),
            digest="sha256:" + hashlib.sha256(payload).hexdigest(),
            metadata=deepcopy(metadata or {}),
        )
        await self.get_session(session_id)
        async with self._session_operation(session_id):
            self._authorize_session_actor_locked(session_id, context)
            return await self._put_attachment_locked(session_id, reference, payload)

    async def _put_attachment_locked(self, session_id, reference, payload):
        session = self._sessions[session_id]
        existing = session.attachments.get(reference.artifact_id)
        if existing is not None:
            if (
                existing != reference
                or await self._read_attachment_bytes(session_id, reference.artifact_id)
                != payload
            ):
                raise self._attachment_error(
                    "artifact.id_conflict",
                    "Immutable session attachment already has different content.",
                )
            return existing.model_copy(deep=True)
        session.attachments[reference.artifact_id] = reference.model_copy(deep=True)
        self._attachment_payloads[(session_id, reference.artifact_id)] = payload
        session.revision += 1
        session.updated_at = self._clock()
        session.revision_sequences[session.revision] = session.last_sequence
        await self._settle_storage(self._commit_storage_locked(session_id))
        return reference.model_copy(deep=True)

    async def get_attachment(self, session_id, artifact_id, *, context):
        await self.get_session(session_id)
        async with self._session_operation(session_id):
            self._authorize_session_actor_locked(session_id, context)
            reference = self._sessions[session_id].attachments.get(artifact_id)
            if reference is None:
                raise self._attachment_error(
                    "artifact.not_found", "Session attachment was not found."
                )
            payload = await self._read_attachment_bytes(session_id, artifact_id)
            self._validate_attachment(reference, payload)

        async def stream():
            yield payload

        return reference.model_copy(deep=True), stream()

    async def copy_attachment(
        self, source_session_id, target_session_id, artifact_id, *, context
    ):
        await self.get_session(source_session_id)
        await self.get_session(target_session_id)
        async with self._session_operation(source_session_id, target_session_id):
            self._authorize_session_actor_locked(source_session_id, context)
            self._authorize_session_actor_locked(target_session_id, context)
            reference = self._sessions[source_session_id].attachments.get(artifact_id)
            if reference is None:
                raise self._attachment_error(
                    "artifact.not_found", "Source session attachment was not found."
                )
            payload = await self._read_attachment_bytes(source_session_id, artifact_id)
            self._validate_attachment(reference, payload)
            return await self._put_attachment_locked(
                target_session_id, reference, payload
            )

    async def _inherit_attachments_locked(self, source_session_id, target_session_id):
        source = self._sessions[source_session_id]
        target = self._sessions[target_session_id]
        for artifact_id, reference in source.attachments.items():
            payload = await self._read_attachment_bytes(source_session_id, artifact_id)
            self._validate_attachment(reference, payload)
            target.attachments[artifact_id] = reference.model_copy(deep=True)
            self._attachment_payloads[(target_session_id, artifact_id)] = payload

    async def _read_attachment_bytes(self, session_id, artifact_id):
        try:
            return self._attachment_payloads[(session_id, artifact_id)]
        except KeyError as exc:
            raise self._attachment_error(
                "artifact.not_found", "Session attachment bytes were not found."
            ) from exc

    def _pending_attachments(self, session_id):
        return tuple(
            (artifact_id, payload)
            for (owner, artifact_id), payload in self._attachment_payloads.items()
            if owner == session_id
        )

    def _forget_attachment_bytes(self, session_id):
        for key in tuple(self._attachment_payloads):
            if key[0] == session_id:
                self._attachment_payloads.pop(key)

    async def get_run_context(self, run_id):
        await self.get_run(run_id)
        async with self._run_session_read(run_id):
            context = self._runs[run_id].request_context
            if context is None:
                raise self._attachment_error(
                    "session.owner_unknown", "Run has no durable request context."
                )
            return context.model_copy(deep=True)

    async def export_session_backup(self, session_id, *, context):
        await self.get_session(session_id)
        descendants = await self.list_descendant_sessions(session_id)
        ids = (session_id, *(row.session_id for row in descendants))
        async with self._session_operation(*ids):
            entries = []
            for owner in ids:
                self._authorize_session_actor_locked(owner, context)
                attachments = []
                for artifact_id, reference in self._sessions[owner].attachments.items():
                    payload = await self._read_attachment_bytes(owner, artifact_id)
                    self._validate_attachment(reference, payload)
                    attachments.append(
                        {
                            "reference": reference.model_dump(mode="json"),
                            "content_base64": base64.b64encode(payload).decode("ascii"),
                        }
                    )
                entries.append(
                    {
                        "format": "sage.session-backup/v1",
                        "state": self._dump_session_state_locked(owner),
                        "attachments": attachments,
                    }
                )
            entries[0]["descendants"] = entries[1:]
            return entries[0]

    def _validate_backup_entry(self, backup, context):
        # Validate the complete backup before changing any destination state.
        if (
            not isinstance(backup, dict)
            or backup.get("format") != "sage.session-backup/v1"
        ):
            raise self._attachment_error(
                "session.backup_invalid", "Unsupported session backup format."
            )
        try:
            state = deepcopy(backup["state"])
            if not isinstance(state, dict):
                raise ValueError("state must be an object")
            probe = self._backup_probe()
            probe._load_state_locked(state)
        except (KeyError, ValueError, TypeError) as exc:
            raise self._attachment_error(
                "session.backup_invalid", "Invalid session backup state."
            ) from exc
        if len(probe._sessions) != 1:
            raise self._attachment_error(
                "session.backup_invalid", "Backup must contain exactly one session."
            )
        session_id = next(iter(probe._sessions))
        probe._authorize_session_actor_locked(session_id, context)
        payloads = {}
        try:
            for entry in backup.get("attachments", ()):
                reference = ArtifactRef.model_validate(entry["reference"])
                payload = base64.b64decode(entry["content_base64"], validate=True)
                self._validate_attachment(reference, payload)
                if (
                    reference
                    != probe._sessions[session_id].attachments.get(
                        reference.artifact_id
                    )
                    or reference.artifact_id in payloads
                ):
                    raise ValueError("attachment reference mismatch")
                payloads[reference.artifact_id] = payload
            if set(payloads) != set(probe._sessions[session_id].attachments):
                raise ValueError("backup is missing attachment bytes")
        except (ValueError, KeyError, TypeError) as exc:
            raise self._attachment_error(
                "session.backup_invalid",
                "Backup attachment content does not match its manifest.",
            ) from exc
        if any(row.session_id != session_id for row in probe._runs.values()):
            raise self._attachment_error(
                "session.backup_invalid", "Backup contains runs from another session."
            )
        return session_id, state, probe, payloads

    async def restore_session_backup(self, backup, *, context):
        entries = [
            self._validate_backup_entry(entry, context)
            for entry in (backup, *backup.get("descendants", ()))
        ]
        for name in (
            "_runs",
            "_checkpoints",
            "_suspensions",
            "_interactions",
            "_session_commit_proposals",
            "_start_idempotency",
        ):
            seen = set()
            for _, _, probe, _ in entries:
                incoming = set(getattr(probe, name))
                if seen & incoming:
                    raise self._attachment_error(
                        "session.backup_invalid",
                        "Backup sessions share conflicting identities.",
                    )
                seen.update(incoming)
        root = entries[0][0]
        ids = [entry[0] for entry in entries]
        if len(set(ids)) != len(ids):
            raise self._attachment_error(
                "session.backup_invalid", "Duplicate session in backup."
            )
        # Ancestor-first storage paths; reject unrelated children and cycles.
        ordered = [entries[0]]
        remaining = entries[1:]
        while remaining:
            parents = {entry[0] for entry in ordered}
            ready = [
                entry
                for entry in remaining
                if entry[2]._sessions[entry[0]].parent_session_id in parents
            ]
            if not ready:
                raise self._attachment_error(
                    "session.backup_invalid", "Invalid backup session tree."
                )
            ordered.extend(ready)
            remaining = [
                entry
                for entry in remaining
                if entry[0] not in {row[0] for row in ready}
            ]
        # Cold durable stores must load existing identities before conflict checks.
        for sid, _, probe, _ in ordered:
            try:
                await self.get_session(sid)
            except SageV2Error as exc:
                if exc.info.code != "session.not_found":
                    raise
            for run_id in probe._runs:
                try:
                    await self.get_run(run_id)
                except SageV2Error as exc:
                    if exc.info.code not in {"run.not_found", "run_id.not_found"}:
                        raise
        # Validate all entries before writing any. Each session commits atomically;
        # exact already-restored sessions make interruption/retry resumable.
        for sid, state, probe, payloads in ordered:
            async with self._session_read(sid):
                await self._check_backup_destination(sid, state, probe, payloads)
        for entry in ordered:
            await self._restore_backup_entry(*entry)
        return await self.get_session(root)

    async def _check_backup_destination(self, session_id, state, probe, payloads):
        if session_id in self._sessions:
            if self._dump_session_state_locked(session_id) != state:
                raise self._attachment_error(
                    "session.backup_conflict",
                    "Destination session differs from the backup.",
                )
            for artifact_id, payload in payloads.items():
                if (
                    await self._read_attachment_bytes(session_id, artifact_id)
                    != payload
                ):
                    raise self._attachment_error(
                        "artifact.integrity_failed",
                        "Restored attachment differs from backup.",
                    )
            return True
        for incoming, existing in (
            (probe._runs, self._runs),
            (probe._checkpoints, self._checkpoints),
            (probe._suspensions, self._suspensions),
            (probe._interactions, self._interactions),
            (probe._session_commit_proposals, self._session_commit_proposals),
            (probe._start_idempotency, self._start_idempotency),
        ):
            if incoming.keys() & existing.keys():
                raise self._attachment_error(
                    "session.backup_conflict",
                    "Backup identities conflict with destination state.",
                )
        return False

    async def _restore_backup_entry(self, session_id, state, probe, payloads):
        async with self._session_operation(session_id):
            if await self._check_backup_destination(session_id, state, probe, payloads):
                return
            self._restore_session_snapshots_locked({session_id: state})
            self._attachment_payloads.update(
                {(session_id, key): value for key, value in payloads.items()}
            )
            await self._settle_storage(self._commit_storage_locked(session_id))

    @staticmethod
    def _validate_attachment(reference, payload):
        if (
            reference.size_bytes != len(payload)
            or reference.digest != "sha256:" + hashlib.sha256(payload).hexdigest()
        ):
            raise SessionAttachmentMixin._attachment_error(
                "artifact.integrity_failed",
                "Session attachment checksum does not match.",
            )

    @staticmethod
    def _attachment_error(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )
