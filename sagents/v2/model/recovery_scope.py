"""Task-local recovery accounting; hosts persist reservations before network calls."""

import asyncio
from datetime import datetime, timezone
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sagents.v2.contracts.model_recovery import ModelRecoveryConfig, ModelRecoveryState


@dataclass
class RecoveryScope:
    config: ModelRecoveryConfig = field(default_factory=ModelRecoveryConfig)
    clock: Any = field(default=lambda: datetime.now(timezone.utc), repr=False)
    run_requests: int = 0
    states: dict[str, ModelRecoveryState] = field(default_factory=dict)
    persist: Any = None
    record_failed_usage: Any = None
    check: Any = None
    reservation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    step_key: str = "operation"
    episode_counts: dict[str, int] = field(default_factory=dict)
    episode_deadlines: dict[str, Any] = field(default_factory=dict)
    active_operations: int = 0
    operation_failed: bool = False
    primary_recovery: bool = False
    closed_episodes: set[str] = field(default_factory=set)
    active_calls: set[str] = field(default_factory=set)
    deadline_guards: dict = field(default_factory=dict, repr=False)

    @asynccontextmanager
    async def enforce_deadline(self):
        """Reschedule running calls when nested negotiation starts recovery."""
        from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory, SageV2Error
        guard = asyncio.timeout(None)
        try:
            async with guard:
                self.deadline_guards[guard] = self.step_key
                self.refresh_deadlines()
                yield
        except TimeoutError as exc:
            if not guard.expired():
                raise
            raise SageV2Error(RuntimeErrorInfo(code="model.recovery_exhausted",
                category=ErrorCategory.VALIDATION, message="Model recovery deadline reached",
                safe_to_resume=True)) from exc
        finally:
            self.deadline_guards.pop(guard, None)

    def refresh_deadlines(self):
        for guard, key in tuple(self.deadline_guards.items()):
            deadline = self.episode_deadlines.get(key)
            if deadline is not None and not guard.expired():
                when = asyncio.get_running_loop().time() + max(0, (deadline - self.clock()).total_seconds())
                if guard.when() is None or when < guard.when():
                    guard.reschedule(when)

    def clear_episode(self, key):
        self.episode_counts.pop(key, None)
        self.episode_deadlines.pop(key, None)
        for state_key in tuple(self.states):
            if state_key.startswith(f"{key}:"):
                self.states.pop(state_key)
        self.closed_episodes.add(key)

    async def finish_episode(self):
        """Persist semantic success before releasing local limits, never Run totals."""
        from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory
        from sagents.v2.contracts.model_recovery import ModelRecoveryDecision, ModelRecoveryAction, ModelFailureKind
        async with self.reservation_lock:
            key = self.step_key
            if not self.episode_counts.get(key):
                return
            if self.persist is not None:
                await self.persist(f"{key}:episode", ModelRecoveryState(run_requests=self.run_requests),
                    RuntimeErrorInfo(code="model.recovery_completed", category=ErrorCategory.VALIDATION,
                        message="Model recovery episode completed", metadata={
                            "recovery_phase": "recovery_completed", "episode_closed": True}),
                    ModelRecoveryDecision(action=ModelRecoveryAction.REPAIR_REQUEST,
                        kind=ModelFailureKind.UNKNOWN, reason="episode_completed"))
            self.clear_episode(key)

    async def reserve(self, key, state, error, decision):
        async with self.reservation_lock:
            if self.check is not None:
                await self.check()
            # Decisions can race while the host check awaits storage. Recheck
            # the category budget under the same lock as shared accounting.
            previous = self.states.get(key)
            if previous is not None and decision.counter is not None:
                from sagents.v2.contracts.errors import (
                    RuntimeErrorInfo, ErrorCategory, SageV2Error,
                )
                consumed = previous.counts.get(decision.counter, 0)
                if consumed >= decision.limit:
                    raise SageV2Error(RuntimeErrorInfo(
                        code="model.recovery_exhausted",
                        category=ErrorCategory.VALIDATION,
                        message="Model recovery category budget exhausted",
                        safe_to_resume=True,
                    ))
                counts = dict(previous.counts)
                for counter, count in state.counts.items():
                    counts[counter] = max(counts.get(counter, 0), count)
                counts[decision.counter] = max(counts[decision.counter], consumed + 1)
                state = state.model_copy(update={"counts": counts})
            state = self.account(state)
            self.states[key] = state
            if self.persist is not None:
                await self.persist(key, state, error, decision)
            return state

    async def record_dispatch(self, key, state, *, completed=False):
        from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory
        from sagents.v2.contracts.model_recovery import (
            ModelRecoveryDecision,
            ModelFailureKind,
        )

        if state.pending_action is None:
            return state
        decision = ModelRecoveryDecision(
            action=state.pending_action,
            kind=state.pending_kind or ModelFailureKind.UNKNOWN,
            reason="dispatch_state",
        )
        state = state.model_copy(
            update={
                "dispatch_started": not completed,
                "pending_action": None if completed else state.pending_action,
            }
        )
        async with self.reservation_lock:
            previous = self.states.get(key)
            if previous is not None and any(previous.counts.get(counter, 0) > state.counts.get(counter, 0)
                for counter in previous.counts):
                from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory, SageV2Error
                raise SageV2Error(RuntimeErrorInfo(code="model.provider_state_invalid",
                    category=ErrorCategory.VALIDATION,
                    message="Stale recovery dispatch cannot replace a newer reservation."))
            self.states[key] = state
            if self.persist is not None:
                await self.persist(
                    key,
                    state,
                    RuntimeErrorInfo(
                        code="model.recovery_dispatch",
                        category=ErrorCategory.VALIDATION,
                        message="Model recovery dispatch state",
                        metadata={
                            "recovery_phase": "recovery_completed"
                            if completed
                            else "recovery_dispatched"
                        },
                    ),
                    decision,
                )
        return state

    async def complete_call(self, key, state):
        await self.record_dispatch(key, state, completed=True)
        # Nested compatibility reservations are finished with this response;
        # replay must not mistake them for another pending logical call.
        for child_key, child in tuple(self.states.items()):
            if child_key.startswith(f"{key}:"):
                await self.record_dispatch(child_key, child, completed=True)
        self.states.pop(key, None)

    async def wait(self, seconds):
        if self.check is None:
            await asyncio.sleep(seconds)
            return
        end = asyncio.get_running_loop().time() + seconds
        while True:
            await self.check()
            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.25, remaining))

    def account(self, state):
        from sagents.v2.contracts.errors import (
            RuntimeErrorInfo,
            ErrorCategory,
            SageV2Error,
        )

        count = self.episode_counts.get(self.step_key, 0)
        deadline = self.episode_deadlines.get(self.step_key, state.deadline)
        if (
            self.run_requests >= self.config.run_requests
            or count >= self.config.episode_requests
            or (deadline and self.clock() >= deadline)
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.recovery_exhausted",
                    category=ErrorCategory.VALIDATION,
                    message="Shared model recovery budget exhausted",
                    safe_to_resume=True,
                )
            )
        self.run_requests += 1
        self.closed_episodes.discard(self.step_key)
        self.episode_counts[self.step_key] = count + 1
        self.episode_deadlines[self.step_key] = deadline
        self.refresh_deadlines()
        return state.model_copy(
            update={
                "run_requests": self.run_requests,
                "episode_requests": count + 1,
                "deadline": deadline,
            }
        )


_active: ContextVar[RecoveryScope | None] = ContextVar(
    "model_recovery_scope", default=None
)
_operation: ContextVar[RecoveryScope | None] = ContextVar("model_recovery_operation", default=None)


def current_recovery_scope():
    return _active.get()


@contextmanager
def recovery_scope(scope=None):
    value = scope or _active.get() or RecoveryScope()
    token = _active.set(value)
    try:
        yield value
    finally:
        _active.reset(token)


async def reserve_additional_request(kind, *, purpose, error=None):
    """Account for parameter negotiation/context/validator retries outside transport."""
    from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory, SageV2Error
    from sagents.v2.contracts.model_recovery import (
        ModelRecoveryAction,
        ModelRecoveryDecision,
        ModelFailureKind,
    )
    from sagents.v2.model.recovery_policy import reserve_recovery

    scope = _active.get()
    if scope is None:
        return  # Direct provider use still has locally bounded negotiations.
    key = f"{_call_key.get() or scope.step_key}:{purpose}" if kind == "compatibility" else f"{scope.step_key}:{purpose}"
    state = scope.states.get(key, ModelRecoveryState()).model_copy(
        update={"run_requests": scope.run_requests}
    )
    now = scope.clock()
    limit = {
        "compatibility": scope.config.compatibility_repairs,
        "context": scope.config.context_repairs,
        "arguments": scope.config.argument_repairs,
        "transient": scope.config.transient_retries,
    }.get(kind, scope.config.episode_requests)
    if (
        state.counts.get(kind, 0) >= limit
        or state.episode_requests >= scope.config.episode_requests
        or scope.run_requests >= scope.config.run_requests
        or (state.deadline and now >= state.deadline)
    ):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="model.recovery_exhausted",
                category=ErrorCategory.VALIDATION,
                message="Model recovery request budget exhausted",
                safe_to_resume=True,
            )
        )
    error = error or RuntimeErrorInfo(
        code="model.request_repair",
        category=ErrorCategory.VALIDATION,
        message="Repairing a model request",
    )
    decision = ModelRecoveryDecision(
        action=ModelRecoveryAction.REPAIR_REQUEST,
        reason=purpose,
        kind=ModelFailureKind.CONTEXT
        if kind == "context"
        else ModelFailureKind.INVALID_REQUEST,
        counter=kind,
        limit=limit,
    )
    state = reserve_recovery(
        state, decision, scope.config, now=now, logical_call_id=key, error=error
    )
    await scope.reserve(key, state, error, decision)


def scoped_recovery(function):
    """Use a caller's scope or isolate a standalone operation (never global state)."""
    from functools import wraps

    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with recovery_operation():
            return await function(*args, **kwargs)

    return wrapped


@asynccontextmanager
async def recovery_operation():
    """Only the outer semantic operation can close nested recovery budgets."""
    with recovery_scope() as scope:
        outer = _operation.get() is not scope
        token = _operation.set(scope)
        if outer:
            if not scope.active_operations:
                scope.operation_failed = False
            scope.active_operations += 1
        succeeded = False
        try:
            yield scope
            succeeded = True
        finally:
            _operation.reset(token)
            if outer:
                scope.operation_failed = scope.operation_failed or not succeeded
                scope.active_operations -= 1
                if (not scope.operation_failed and not scope.active_operations and not scope.primary_recovery
                    and f"{scope.step_key}:output_repair" not in scope.states):
                    await scope.finish_episode()


async def schedule_failure_recovery(error, *, purpose, key=None, transient_retries=None):
    """Reserve a policy decision for an outer operation with its own timeout."""
    import random
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.contracts.model_recovery import ModelRecoveryAction
    from sagents.v2.model.recovery_policy import ModelRecoveryPolicy, reserve_recovery

    scope = _active.get()
    if scope is None:
        raise RuntimeError("Recovery requires an operation scope")
    key = key or f"{scope.step_key}:{purpose}"
    state = scope.states.get(key, ModelRecoveryState()).model_copy(
        update={
            "run_requests": scope.run_requests,
            "episode_requests": scope.episode_counts.get(scope.step_key, 0),
            "deadline": scope.episode_deadlines.get(scope.step_key),
        }
    )
    now = scope.clock()
    config = scope.config
    if transient_retries is not None:
        config = config.model_copy(update={"transient_retries": min(transient_retries, config.transient_retries)})
    decision = ModelRecoveryPolicy().decide(
        error,
        state,
        config,
        now=now,
        purpose=purpose,
        jitter=random.uniform(0, 0.25),
    )
    if decision.action == ModelRecoveryAction.STOP_WITH_EXPLANATION:
        raise SageV2Error(
            error.model_copy(
                update={
                    "metadata": {
                        **error.metadata,
                        "recovery": {
                            "version": "model-recovery/1",
                            **decision.model_dump(mode="json"),
                        },
                    }
                }
            )
        )
    state = reserve_recovery(
        state, decision, scope.config, now=now, logical_call_id=key, error=error
    )
    await scope.reserve(key, state, error, decision)
    return decision


_call_key: ContextVar[str | None] = ContextVar("model_recovery_call_key", default=None)


@contextmanager
def recovery_call(request, purpose):
    """Claim one logical call; identical concurrent calls never adopt each other.

    A semantic fingerprint finds a pending reservation after request IDs are
    rebuilt on restart. Multiple matching reservations are ambiguous, not guessed.
    Old purpose-only keys are accepted only while unclaimed.
    """
    import hashlib
    import json
    from sagents.v2.contracts.common import new_id
    from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory, SageV2Error
    scope = current_recovery_scope()
    purpose = purpose or getattr(request, "metadata", {}).get("purpose", "auxiliary")
    legacy = f"{scope.step_key}:{purpose}"
    semantic = request.model_dump(mode="json", exclude={"request_id"})
    digest = hashlib.sha256(json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prefix = f"{legacy}:call:{digest}:"
    candidates = set()
    for saved_key, state in scope.states.items():
        if state.pending_action is None:
            continue
        if saved_key == legacy:
            candidate = legacy
        elif saved_key.startswith(prefix):
            # Compatibility reservations live below their logical call. They
            # can identify it after a crash before the parent had to retry.
            candidate = prefix + saved_key[len(prefix):].split(":", 1)[0]
        else:
            continue
        if candidate not in scope.active_calls:
            candidates.add(candidate)
    if len(candidates) > 1:
        raise SageV2Error(RuntimeErrorInfo(code="model.provider_state_invalid",
            category=ErrorCategory.VALIDATION,
            message="Multiple pending model calls match the restored request; cannot resume safely."))
    key = next(iter(candidates)) if candidates else prefix + new_id("call")
    if key in scope.active_calls:
        key = prefix + new_id("call")
    scope.active_calls.add(key)
    token = _call_key.set(key)
    try:
        yield key
    finally:
        _call_key.reset(token)
        scope.active_calls.discard(key)


async def resume_pending_recovery(scope, key, purpose):
    """Honor durable waits; uncertain dispatched requests consume another slot."""
    from sagents.v2.contracts.model_recovery import ModelFailure, ModelFailureKind
    from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory
    state = scope.states.get(key, ModelRecoveryState())
    if state.pending_action is not None:
        if state.deadline is not None:
            existing = scope.episode_deadlines.get(scope.step_key)
            scope.episode_deadlines[scope.step_key] = min(existing, state.deadline) if existing else state.deadline
        if state.dispatch_started:
            error = RuntimeErrorInfo(code="model.recovery_interrupted", category=ErrorCategory.VALIDATION,
                message="A previous model recovery request may have been sent.", safe_to_resume=True,
                metadata={"model_failure": ModelFailure(kind=state.pending_kind or ModelFailureKind.UNKNOWN).model_dump(mode="json")})
            await schedule_failure_recovery(error, purpose=purpose, key=key)
            state = scope.states[key]
        if state.retry_not_before is not None:
            async with scope.enforce_deadline():
                await scope.wait(max(0, (state.retry_not_before - scope.clock()).total_seconds()))
    return state
