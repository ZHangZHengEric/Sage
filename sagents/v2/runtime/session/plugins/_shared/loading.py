"""Lazy durable Session access over the canonical coordinator semantics."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, aclosing
from sagents.v2.contracts.errors import SageV2Error
from .aggregate import DurableAggregateCache
from .cache import cached_session_operation


class DurableSessionLoading(DurableAggregateCache):
    @cached_session_operation
    async def create_run(self, command, context):
        await self._ensure_ready()
        if command.parent_run_id:
            await self._ensure_resource_loaded("runs", "run_id", command.parent_run_id)
        if command.session_id is not None:
            await self._ensure_session_loaded(command.session_id, missing_ok=True)
        else:
            lookup = await self._read_start_lookup(command, context)
            if lookup is not None:
                await self._ensure_session_loaded(lookup)
        return await super().create_run(command, context)

    @cached_session_operation
    async def get_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().get_session(session_id)

    @cached_session_operation
    async def authorize_session_actor(self, session_id, context):
        await self._ensure_session_loaded(session_id)
        await super().authorize_session_actor(session_id, context)

    @cached_session_operation
    async def delete_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        result = await super().delete_session(session_id)
        self._loaded_session_ids.intersection_update(self._sessions)
        self._session_cache.evicted_suspended.discard(session_id)
        return result

    async def has_nonterminal_runs(self):
        return (
            bool(self._session_cache.evicted_suspended)
            or await super().has_nonterminal_runs()
        )

    @cached_session_operation
    async def get_execution_resource(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_execution_resource(run_id)

    @cached_session_operation
    async def commit_execution_resource(self, *, record, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", record.run_id)
        return await super().commit_execution_resource(record=record, **kwargs)

    @cached_session_operation
    async def get_run_context(self, run_id):
        return await super().get_run_context(run_id)

    @cached_session_operation
    async def put_attachment(self, session_id, **kwargs):
        return await super().put_attachment(session_id, **kwargs)

    @cached_session_operation
    async def get_attachment(self, session_id, artifact_id, **kwargs):
        return await super().get_attachment(session_id, artifact_id, **kwargs)

    @cached_session_operation
    async def copy_attachment(
        self, source_session_id, target_session_id, artifact_id, **kwargs
    ):
        return await super().copy_attachment(
            source_session_id, target_session_id, artifact_id, **kwargs
        )

    @cached_session_operation
    async def export_session_backup(self, session_id, **kwargs):
        return await super().export_session_backup(session_id, **kwargs)

    @cached_session_operation
    async def restore_session_backup(self, backup, **kwargs):
        return await super().restore_session_backup(backup, **kwargs)

    @cached_session_operation
    async def list_session_runs(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_runs(session_id)

    @cached_session_operation
    async def list_descendant_sessions(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        return await super().list_descendant_sessions(session_id)

    @cached_session_operation
    async def read_session_events(self, session_id, **kwargs):
        await self._ensure_session_loaded(session_id)
        return await super().read_session_events(session_id, **kwargs)

    @cached_session_operation
    async def list_session_commit_proposals(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_commit_proposals(session_id)

    @cached_session_operation
    async def get_run(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run(run_id)

    @cached_session_operation
    async def get_run_result(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run_result(run_id)

    @cached_session_operation
    async def find_start_run(self, session_id, idempotency_key, context):
        try:
            await self._ensure_session_loaded(session_id, missing_ok=True)
            return await super().find_start_run(session_id, idempotency_key, context)
        except SageV2Error as exc:
            # A deleted Session has no matching start, including when Redis
            # detects its tombstone while preparing the guarded read.
            if exc.info.code == "session.not_found":
                return None
            raise

    @cached_session_operation
    async def get_start_command(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_start_command(run_id)

    @cached_session_operation
    async def get_latest_checkpoint(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_latest_checkpoint(run_id)

    @cached_session_operation
    async def read_events(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_events(run_id, **kwargs)

    @cached_session_operation
    async def read_stream_previews(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_stream_previews(run_id, **kwargs)

    @cached_session_operation
    async def publish_stream_preview(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().publish_stream_preview(run_id=run_id, **kwargs)

    @cached_session_operation
    async def commit_model_stream_batch(self, *, run, drafts, context, idempotency_key):
        """Persist item starts; send model deltas from the in-process buffer."""

        return await self._commit_model_stream_with_previews(
            run=run,
            drafts=drafts,
            context=context,
            idempotency_key=idempotency_key,
        )

    @cached_session_operation
    async def read_fork_base_events(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_fork_base_events(run_id)

    @cached_session_operation
    async def commit_run(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().commit_run(run_id=run_id, **kwargs)

    @cached_session_operation
    async def propose_session_commit(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().propose_session_commit(command, context)

    @cached_session_operation
    async def publish_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().publish_session_commit(command, context)

    @cached_session_operation
    async def reject_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().reject_session_commit(command, context)

    @cached_session_operation
    async def get_session_commit_proposal(self, proposal_id):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", proposal_id
        )
        return await super().get_session_commit_proposal(proposal_id)

    @cached_session_operation
    async def get_checkpoint(self, checkpoint_id):
        await self._ensure_resource_loaded(
            "checkpoints", "checkpoint_id", checkpoint_id
        )
        return await super().get_checkpoint(checkpoint_id)

    @cached_session_operation
    async def get_suspension(self, suspension_id):
        await self._ensure_resource_loaded(
            "suspensions", "suspension_id", suspension_id
        )
        return await super().get_suspension(suspension_id)

    @cached_session_operation
    async def get_interaction(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction(interaction_id)

    @cached_session_operation
    async def get_interaction_resolution(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction_resolution(interaction_id)

    @cached_session_operation
    async def enqueue_steer(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().enqueue_steer(command, context)

    @cached_session_operation
    async def claim_steers(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().claim_steers(run_id=run_id, **kwargs)

    @cached_session_operation
    async def list_steers(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().list_steers(run_id)

    @cached_session_operation
    async def resolve_interaction(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().resolve_interaction(command, context)

    @cached_session_operation
    async def request_resume(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().request_resume(command, context)

    async def subscribe_events(self, cursor):
        retained = None
        try:
            async with self._session_cache.operation():
                await self._ensure_resource_loaded("runs", "run_id", cursor.run_id)
                sid = self._runs[cursor.run_id].session_id
                self._session_cache.retain(sid)
                retained = sid
            # Close the coordinator iterator before dropping its cache pin, even
            # when the transport closes this generator from a different Task.
            async with aclosing(super().subscribe_events(cursor)) as events:
                async for event in events:
                    yield event
        finally:
            if retained is not None:
                self._session_cache.release(retained)
                await self._session_cache.prune()

    async def _ensure_session_loaded(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        self._session_cache.pin(session_id)
        if session_id in self._loaded_session_ids:
            return
        await self._ensure_ready()
        lock = self._load_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            if session_id in self._loaded_session_ids:
                return
            payload = await self._fetch_session(session_id)
            if payload is None:
                if missing_ok:
                    return
                raise self._not_found("session.not_found", session_id)
            prepared = await asyncio.to_thread(self._prepare_session, payload)
            async with self._lock:
                if session_id not in self._loaded_session_ids:
                    self._install_session_locked(payload, prepared=prepared)

    async def _ensure_descendants_loaded(self, session_id: str) -> None:
        await self._ensure_ready()
        await self._ensure_sessions_loaded(await self._list_descendant_ids(session_id))

    async def _ensure_sessions_loaded(self, session_ids) -> None:
        """Install cold aggregates in batches while sharing single-load locks."""
        ids = tuple(sorted(set(session_ids)))
        for sid in ids:
            self._session_cache.pin(sid)
        missing = [sid for sid in ids if sid not in self._loaded_session_ids]
        if not missing:
            return
        await self._ensure_ready()
        async with AsyncExitStack() as locks:
            for sid in missing:
                await locks.enter_async_context(
                    self._load_locks.setdefault(sid, asyncio.Lock())
                )
            # A single loader may have installed a Session while we acquired its
            # lock. Keep that live identity and fetch only still-cold Sessions.
            missing = [sid for sid in missing if sid not in self._loaded_session_ids]
            if not missing:
                return
            payloads = await self._fetch_sessions(missing)

            def prepare():
                return {
                    sid: self._prepare_session(payloads[sid])
                    for sid in missing
                    if sid in payloads
                }

            prepared = await asyncio.to_thread(prepare)
            async with self._lock:
                for sid in missing:
                    if sid in prepared and sid not in self._loaded_session_ids:
                        self._install_session_locked(
                            payloads[sid], prepared=prepared[sid]
                        )

    async def _list_descendant_ids(self, session_id: str) -> list[str]:
        return await self.list_workspace_descendant_ids([session_id])

    async def _ensure_resource_loaded(
        self, collection: str, identity_key: str, identity: str
    ) -> None:
        if self._resource_is_loaded(collection, identity):
            row = getattr(self, "_" + collection)[identity]
            sid = getattr(row, "session_id", None) or self._runs[row.run_id].session_id
            self._session_cache.pin(sid)
            return
        await self._ensure_ready()
        session_id = await self._locate_session(identity_key, identity)
        if session_id is None:
            raise self._not_found(f"{identity_key}.not_found", identity)
        await self._ensure_session_loaded(session_id)
        if not self._resource_is_loaded(collection, identity):
            raise self._not_found(f"{identity_key}.not_found", identity)

    def _resource_is_loaded(self, collection: str, identity: str) -> bool:
        mappings = {
            "runs": self._runs,
            "checkpoints": self._checkpoints,
            "suspensions": self._suspensions,
            "interactions": self._interactions,
            "session_commit_proposals": self._session_commit_proposals,
        }
        return identity in mappings[collection]
