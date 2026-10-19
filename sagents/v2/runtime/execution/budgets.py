"""Run-tree budget checks derived from durable commands and usage events.

Budgets are checked before new work. Already dispatched concurrent inference
can report usage beyond a ceiling; it must settle rather than hide its cost.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo


@dataclass(frozen=True)
class RunBudget:
    deadline: datetime | None = None
    remaining_tokens: int | None = None
    error: RuntimeErrorInfo | None = None


async def run_tree_runs(store, run):
    """Select exact execution ancestry, excluding unrelated Session turns."""
    sessions = (
        await store.get_session(run.session_id),
        *await store.list_descendant_sessions(run.session_id),
    )
    rows = [
        row
        for session in sessions
        for row in await store.list_session_runs(session.session_id)
    ]
    commands = {row.run_id: await store.get_start_command(row.run_id) for row in rows}
    included = {run.run_id}
    while True:
        children = {
            key
            for key, command in commands.items()
            if command.parent_run_id in included
        }
        if children <= included:
            break
        included.update(children)
    return tuple(row for row in rows if row.run_id in included)


async def run_tree_tokens(store, run, *, usage_cache=None) -> int:
    """Count this execution's durable usage, including all descendants."""
    rows = await run_tree_runs(store, run)
    cache = {} if usage_cache is None else usage_cache
    snapshots = {row.run_id: row for row in rows}
    total = 0
    for run_id in snapshots:
        sequence, tokens = cache.get(run_id, (0, 0))
        current_sequence = snapshots[run_id].last_run_sequence
        if current_sequence < sequence:
            sequence, tokens = 0, 0
        if current_sequence != sequence:
            events = await store.read_events(run_id, after_sequence=sequence)
            tokens += sum(
                event.data.usage.input_tokens + event.data.usage.output_tokens
                for event in events
                if event.type == "usage.recorded"
            )
            sequence = events[-1].run_sequence if events else sequence
            cache[run_id] = sequence, tokens
        total += tokens
    return total


async def stop_budget_descendants(runtime, run, context):
    """Settle deferred descendants before publishing their parent's budget failure."""
    from sagents.v2.contracts.commands import CancelRun, CommandDecision
    from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.runtime.execution.ownership import is_lease_loss

    rows = await run_tree_runs(runtime.session_store, run)
    for row in reversed(rows):
        if row.run_id == run.run_id:
            continue
        for attempt in range(3):
            current = await runtime.get_run(row.run_id)
            if current.state in TERMINAL_RUN_STATES:
                break
            try:
                receipt = await runtime.cancel_run(
                    CancelRun(
                        run_id=current.run_id,
                        expected_revision=current.revision,
                        idempotency_key=f"budget-stop:{run.run_id}:{current.run_id}:{current.revision}",
                        reason="ancestor_budget_exhausted",
                    ),
                    context,
                )
                if receipt.decision == CommandDecision.REJECTED:
                    raise SageV2Error(receipt.error)
                break
            except SageV2Error as exc:
                if (
                    is_lease_loss(exc)
                    or exc.info.category != ErrorCategory.CONFLICT
                    or attempt == 2
                ):
                    raise


async def evaluate_run_budget(
    store, run, now: datetime, *, check_tokens=True, usage_cache=None
) -> RunBudget:
    """Apply every ancestor's absolute deadline and shared subtree token cap."""
    deadline = None
    remaining = None
    current = run
    seen = set()
    while current.run_id not in seen:
        seen.add(current.run_id)
        command = await store.get_start_command(current.run_id)
        if command.config.deadline_seconds is not None:
            limit = current.created_at + timedelta(
                seconds=command.config.deadline_seconds
            )
            deadline = min(deadline, limit) if deadline is not None else limit
            if now >= limit:
                return RunBudget(
                    deadline, remaining, _error("budget.deadline", current.run_id)
                )
        tokens = command.config.max_total_tokens or command.config.metadata.get(
            "max_total_tokens"
        )
        if check_tokens and tokens is not None:
            available = tokens - await run_tree_tokens(
                store, current, usage_cache=usage_cache
            )
            remaining = (
                min(remaining, available) if remaining is not None else available
            )
            if available <= 0:
                return RunBudget(
                    deadline, remaining, _error("budget.max_tokens", current.run_id)
                )
        if command.parent_run_id is None:
            break
        current = await store.get_run(command.parent_run_id)
    return RunBudget(deadline, remaining)


def _error(code, run_id):
    return RuntimeErrorInfo(
        code=code,
        category=ErrorCategory.VALIDATION,
        safe_to_resume=False,
        message="The task tree reached its time limit."
        if code == "budget.deadline"
        else "The task tree reached its total token limit.",
        metadata={"budget_run_id": run_id, "budget_scope": "run_tree"},
    )
