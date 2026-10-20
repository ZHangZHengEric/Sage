"""Small Run read models, independent of execution/event payloads."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from collections.abc import Mapping

from sagents.v2.contracts.run_state import RunState


@dataclass(frozen=True)
class RunMetadata:
    session_id: str
    run_id: str
    created_at: datetime
    state: RunState
    agent_id: str
    invocation_mode: str = ''
    task_name: Any = ''
    admitted_agent_id: str = ''
    session_created_at: datetime | None = None
    parent_session_id: str | None = None


def metadata_from_run(row, command):
    return RunMetadata(row.session_id, row.run_id, row.created_at, RunState(row.state),
        _workspace_agent_id(command.config.metadata, command.agent_id, command.parent_run_id) if command else '',
        (command.invocation_mode or '') if command else '',
        command.config.metadata.get('task_name', '') if command else '', command.agent_id if command else '')


def _workspace_agent_id(metadata, admitted_agent_id, parent_run_id):
    # Root workspace identity predates execution grants. Child Runs retain the
    # admitted package identity, even when they inherit root metadata.
    if parent_run_id:
        return admitted_agent_id
    grant = metadata.get('server_v2.execution', {})
    grant = grant if isinstance(grant, Mapping) else {}
    composition = metadata.get('server_v2.composition', {})
    composition = composition if isinstance(composition, Mapping) else {}
    agent = composition.get('agent', {})
    agent = agent if isinstance(agent, Mapping) else {}
    return grant.get('agent_id') or agent.get('id') or admitted_agent_id


def metadata_page(rows, session_ids, *, after=None, limit=101, agent_id='', states=()):
    from datetime import datetime
    order = {sid: index for index, sid in enumerate(session_ids)}
    selected = [row for row in rows if row.session_id in order and (not agent_id or row.agent_id == agent_id)
                and (not states or row.state in states)]
    selected.sort(key=lambda row: (order[row.session_id], row.created_at, row.run_id))
    if after is not None:
        sid, created_at, rid = after
        key = (order[sid], datetime.fromisoformat(created_at), rid)
        selected = [row for row in selected if (order[row.session_id], row.created_at, row.run_id) > key]
    return tuple(selected[:limit])


def metadata_from_payload(payload):
    from datetime import datetime
    rows = []
    heads = {row['session_id']: row for row in payload.get('sessions', ())}
    for row in payload.get('runs', ()):
        command = row.get('start_command') or {}
        config = command.get('config', {}).get('metadata', {})
        head = heads[row['session_id']]
        agent_id = _workspace_agent_id(config, command.get('agent_id', ''), command.get('parent_run_id'))
        rows.append(RunMetadata(row['session_id'], row['run_id'], datetime.fromisoformat(row['created_at']),
            RunState(row['state']), agent_id,
            command.get('invocation_mode') or '', config.get('task_name', ''), command.get('agent_id', ''),
            datetime.fromisoformat(head['created_at']), head.get('parent_session_id')))
    owners = {row['session_id']: row.get('owner') for row in payload.get('sessions', ())}
    for sid in owners:
        if owners[sid] is not None:
            continue
        candidates = sorted((row for row in payload.get('runs', ()) if row['session_id'] == sid),
                            key=lambda row: (datetime.fromisoformat(row['created_at']), row['run_id']))
        owner = next(((row.get('request_context') or {}).get('actor') for row in candidates
                      if (row.get('request_context') or {}).get('actor') is not None), None)
        if owner is None:
            events = sorted((event for values in payload.get('run_events', {}).values() for event in values
                             if event.get('session_id') == sid), key=lambda event: event['session_sequence'])
            owner = next((event.get('actor') for event in events if event['type'] == 'run.accepted'), None)
        owners[sid] = owner
    return tuple(rows), owners


class RunMetadataQueries:
    async def _run_metadata_batch(self, session_ids):
        selected_ids = set(session_ids)
        async with self._lock:
            from dataclasses import replace
            rows = tuple(replace(metadata_from_run(row, row.start_command),
                         session_created_at=self._sessions[row.session_id].created_at,
                         parent_session_id=self._sessions[row.session_id].parent_session_id) for row in self._runs.values()
                         if row.session_id in selected_ids)
            owners = {}
            for sid in session_ids:
                session = self._sessions.get(sid)
                if session is None:
                    continue
                owner = session.owner
                if owner is None:
                    owner = self._derive_session_owner(sid, runs=self._runs, session_events=self._session_events)
                owners[sid] = owner
            return rows, owners

    async def _run_metadata_rows(self, session_ids):
        rows, _ = await self._run_metadata_batch(session_ids)
        return rows

    async def authorized_run_metadata_page(self, session_ids, context, *, after=None, limit=101, agent_id='', states=()):
        from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
        from sagents.v2.contracts.principals import ActorRef
        if not 1 <= limit <= 201 or len(session_ids) > 200:
            raise ValueError('invalid Run metadata page')
        rows, owners = await self._run_metadata_batch(session_ids)
        allowed = []
        for sid in session_ids:
            if sid not in owners:
                continue
            owner = owners[sid]
            try:
                self._authorize_session_owner(ActorRef.model_validate(owner) if isinstance(owner, dict) else owner, context)
            except SageV2Error as exc:
                if exc.info.category == ErrorCategory.AUTHORIZATION:
                    continue
                raise
            allowed.append(sid)
        if after is not None and after[0] not in allowed:
            # Continue after an inaccessible/deleted current Session by its
            # original position, while exposing no data from it.
            order = {sid: index for index, sid in enumerate(session_ids)}
            allowed = [sid for sid in allowed if order[sid] > order[after[0]]]
            after = None
        return metadata_page(rows, allowed, after=after, limit=limit, agent_id=agent_id, states=states)
