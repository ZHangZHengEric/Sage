# pyright: strict
"""Shared durable Run transition boundary used by Agent and Flow drivers."""

from __future__ import annotations


from collections.abc import Iterable
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.contracts.checkpoint import Checkpoint, Suspension
from sagents.v2.contracts.interactions import InteractionRequest
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunSnapshot, RunState


class DurableRunLifecycle:
    def __init__(self, runtime: RuntimePort) -> None:
        self.runtime = runtime

    async def commit(
        self,
        run: RunSnapshot,
        *,
        new_state: RunState,
        drafts: Iterable[EventDraft],
        context: RequestContext,
        idempotency_key: str,
        expected_states: frozenset[RunState],
        checkpoint: Checkpoint | None = None,
    ) -> RunSnapshot:
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states=expected_states,
            new_state=new_state,
            drafts=tuple(drafts),
            context=context,
            idempotency_key=idempotency_key,
            checkpoint=checkpoint,
        )
        return result.run

    async def suspend(
        self,
        run: RunSnapshot,
        *,
        checkpoint: Checkpoint,
        suspension: Suspension,
        context: RequestContext,
        idempotency_key: str,
        interaction: InteractionRequest | None = None,
    ) -> RunSnapshot:
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=idempotency_key,
        )
