import json

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import SessionAggregateSnapshotV2
from sagents.v2.runtime.session.state import SessionStoreCoordinator


class CapturingStore(SessionStoreCoordinator):
    async def _commit_storage_locked(self, session_id):
        self.delta = self._session_mutation_locked(session_id)


@pytest.mark.asyncio
async def test_run_transition_does_not_rewrite_large_accepted_command():
    store = CapturingStore()
    context = RequestContext(actor=ActorRef(principal_id="owner", principal_type=PrincipalType.USER))
    command = StartRun(agent_id="agent", resolved_spec_hash="spec", idempotency_key="start",
                       input=(InputItem(role="user", content=(TextBlock(text="large input " * 10000),)),))
    created = await store.create_run(command, context)
    before = SessionAggregate(SessionAggregateSnapshotV2.model_validate(
        store._dump_session_state_locked(created.handle.session_id)))
    await store.commit_run(run_id=created.handle.run_id, expected_revision=0,
                           expected_states={RunState.QUEUED}, new_state=RunState.RUNNING,
                           drafts=(), context=context, idempotency_key="running")

    assert len(json.dumps(store.delta.model_dump(mode="json")).encode()) < 10000
    restored = before.apply(store.delta)
    assert restored.snapshot.runs[0].state == RunState.RUNNING
    assert restored.snapshot.runs[0].start_command == command
    assert restored.snapshot.runs[0].request_context == context
    assert len(restored.snapshot.command_results) == 1
