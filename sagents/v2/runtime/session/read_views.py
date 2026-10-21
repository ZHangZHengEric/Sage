"""Bounded read projections of existing Session rows, without execution caches."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.state import SessionStoreCoordinator


from collections.abc import Collection
from dataclasses import dataclass

from sagents.v2.contracts.checkpoint import Suspension
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.errors import ErrorCategory, NotFoundError, RuntimeErrorInfo
from sagents.v2.contracts.interactions import InteractionRequest
from sagents.v2.contracts.principals import ActorRef
from sagents.v2.contracts.run_state import RunSnapshot, RunState


@dataclass(frozen=True)
class RunReadView:
    run: RunSnapshot
    command: StartRun | None
    suspension: Suspension | None
    interaction: InteractionRequest | None
    events: tuple[RuntimeEvent, ...] = ()


@dataclass(frozen=True)
class SessionReadView:
    owner: ActorRef | None
    runs: tuple[RunReadView, ...]


def validate_view_ids(session_ids, run_ids=None):
    ids = tuple(dict.fromkeys(session_ids))
    if len(ids) > 200 or (run_ids is not None and len(set(run_ids)) > 200):
        raise ValueError('Session read views accept at most 200 Session and Run IDs')
    return ids


_COLLECTION_KEYS = {'sessions':'session_id','runs':'run_id','suspensions':'suspension_id','interactions':'interaction_id'}


def project_view_state(state, *, include_events=False, run_ids=None):
    # Ownership must use all Runs, even when the consumer selects only one Run.
    projected: dict[str, Any] = {name: [dict(row) for row in state.get(name, ())] for name in _COLLECTION_KEYS}
    projected['run_events'] = {
        rid: [event for event in values if (include_events and (run_ids is None or rid in run_ids))
              or event.get('type') == 'run.accepted']
        for rid, values in state.get('run_events', {}).items()
    }
    return projected


def apply_view_delta(state, delta, *, include_events=False, run_ids=None):
    for name, key in _COLLECTION_KEYS.items():
        rows = {row[key]:row for row in state[name]}
        for row in delta.get('upserts', {}).get(name, ()):
            rows[row[key]] = dict(row)
        for patch in delta.get('patches', {}).get(name, ()):
            if patch[key] not in rows:
                raise ValueError('Session view patch refers to a missing row')
            rows[patch[key]].update(patch)
        for deleted in delta.get('deletes', {}).get(name, ()):
            rows.pop(deleted[0],None)
        state[name] = list(rows.values())
    for operation in ('replacements','appends'):
        for rid, values in delta.get(operation, {}).get('run_events', {}).items():
            events = project_view_state({'run_events':{rid:values}},include_events=include_events,run_ids=run_ids)['run_events'][rid]
            if operation == 'replacements':
                state['run_events'][rid] = events
            else:
                state['run_events'].setdefault(rid,[]).extend(events)
    for rid in delta.get('map_deletes', {}).get('run_events', ()):
        state['run_events'].pop(rid,None)
    return state


def legacy_owner_sessions(states):
    return [sid for sid,state in states.items() if state['sessions'][0].get('owner') is None
            and not any((run.get('request_context') or {}).get('actor') is not None for run in state['runs'])]


def _missing_reference(code, identity):
    return NotFoundError(RuntimeErrorInfo(code=code,category=ErrorCategory.VALIDATION,
        message=f'resource {identity!r} was not found',retryable=False,safe_to_resume=False))


def views_from_payload(state, *, include_events=False, run_ids=None, suspended_only=False):
    from sagents.v2.runtime.session.run_metadata import metadata_from_payload
    _, owners = metadata_from_payload(state)
    suspensions = {row['suspension_id']:row for row in state.get('suspensions', ())}
    interactions = {row['interaction_id']:row for row in state.get('interactions', ())}
    result = {}
    for head in state.get('sessions', ()):
        sid = head['session_id']
        selected = []
        for row in sorted((r for r in state.get('runs', ()) if r['session_id'] == sid),key=lambda r:(r['created_at'],r['run_id'])):
            if (run_ids is not None and row['run_id'] not in run_ids) or (suspended_only and row['state'] != RunState.SUSPENDED):
                continue
            run = RunSnapshot.model_validate({key:row[key] for key in RunSnapshot.model_fields if key in row})
            raw_command = row.get('start_command')
            if suspended_only and raw_command is None:
                raise _missing_reference('run.header_not_found',run.run_id)
            suspension = suspensions.get(run.suspension_id)
            interaction = interactions.get(suspension.get('interaction_id')) if suspension else None
            if run.suspension_id and suspension is None:
                raise _missing_reference('suspension.not_found',run.suspension_id)
            if suspension and suspension.get('interaction_id') and interaction is None:
                raise _missing_reference('interaction.not_found',suspension['interaction_id'])
            selected.append(RunReadView(run,StartRun.model_validate(raw_command) if raw_command else None,
                Suspension.model_validate(suspension) if suspension else None,
                InteractionRequest.model_validate(interaction) if interaction else None,
                tuple(RuntimeEvent.model_validate(e) for e in state.get('run_events',{}).get(run.run_id,())) if include_events else ()))
        owner = owners.get(sid)
        result[sid] = SessionReadView(ActorRef.model_validate(owner) if owner is not None else None,tuple(selected))
    return result


class SessionReadQueries:
    async def read_session_views(self, session_ids: Collection[str], *, include_events=False, run_ids=None, suspended_only=False):
        store = cast("SessionStoreCoordinator", self)
        ids = validate_view_ids(session_ids,run_ids)
        selected_ids = set(ids)
        async with store._lock:
            result = {}
            rows = {}
            for row in store._runs.values():
                if row.session_id in selected_ids:
                    rows.setdefault(row.session_id,[]).append(row)
            for sid in ids:
                session = store._sessions.get(sid)
                if session is None:
                    continue
                owner = session.owner or store._derive_session_owner(sid,runs=store._runs,session_events=store._session_events)
                selected = []
                for row in sorted(rows.get(sid,()),key=lambda r:(r.created_at,r.run_id)):
                    if (run_ids is not None and row.run_id not in run_ids) or (suspended_only and row.state != RunState.SUSPENDED):
                        continue
                    if suspended_only and row.start_command is None:
                        raise _missing_reference('run.header_not_found',row.run_id)
                    suspension = store._suspensions.get(row.suspension_id) if row.suspension_id else None
                    interaction = store._interactions.get(suspension.interaction_id) if suspension and suspension.interaction_id else None
                    if row.suspension_id and suspension is None:
                        raise _missing_reference('suspension.not_found',row.suspension_id)
                    if suspension and suspension.interaction_id and interaction is None:
                        raise _missing_reference('interaction.not_found',suspension.interaction_id)
                    selected.append(RunReadView(store._run_snapshot(row),row.start_command,suspension,interaction,
                        tuple(store._run_events.get(row.run_id,())) if include_events else ()))
                result[sid] = SessionReadView(owner,tuple(selected))
            return result
