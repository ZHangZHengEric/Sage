# pyright: strict
"""Shared durable Run transition boundary used by Agent and Flow drivers."""

from __future__ import annotations


class DurableRunLifecycle:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    async def commit(
        self,
        run,
        *,
        new_state,
        drafts,
        context,
        idempotency_key,
        expected_states,
    ):
        result = await self.runtime.session_store.commit_run(
            run_id=run.run_id,
            expected_revision=run.revision,
            expected_states=expected_states,
            new_state=new_state,
            drafts=tuple(drafts),
            context=context,
            idempotency_key=idempotency_key,
        )
        return result.run

    async def suspend(
        self,
        run,
        *,
        checkpoint,
        suspension,
        context,
        idempotency_key,
        interaction=None,
    ):
        return await self.runtime.commit_suspension(
            run_id=run.run_id,
            expected_revision=run.revision,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
            context=context,
            idempotency_key=idempotency_key,
        )
