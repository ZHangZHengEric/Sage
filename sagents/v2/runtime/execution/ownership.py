"""Local execution ownership shared with every inline Team task.

Revocation is monotonic: cancelling an obsolete worker must not turn its
recoverable Run tree into terminal failures via an unfenced control runtime.
Durable ownership remains the Scheduler's lease/fence, never this local flag.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from contextlib import contextmanager

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


@dataclass
class ExecutionOwnership:
    revoked: bool = False
    run_id: str | None = None
    supports_deferred_work: bool = False


_INLINE_DEFER: ContextVar[bool | None] = ContextVar("sage_inline_defer", default=None)


@contextmanager
def deferred_work_scope(enabled: bool):
    token = _INLINE_DEFER.set(enabled)
    try:
        yield
    finally:
        _INLINE_DEFER.reset(token)


def can_defer_run(run_id: str) -> bool:
    ownership = ACTIVE_OWNERSHIP.get()
    inline = _INLINE_DEFER.get()
    return bool(
        ownership is not None and not ownership.revoked
        and ownership.supports_deferred_work
        and (inline if inline is not None else ownership.run_id == run_id)
    )


ACTIVE_OWNERSHIP: ContextVar[ExecutionOwnership | None] = ContextVar(
    "sage_execution_ownership", default=None
)


def is_lease_loss(error: BaseException | RuntimeErrorInfo) -> bool:
    info = error.info if isinstance(error, SageV2Error) else error
    return isinstance(info, RuntimeErrorInfo) and info.code in {
        "scheduler.fence_rejected",
        "scheduler.lease_expired",
    }


def revoke_ownership() -> None:
    ownership = ACTIVE_OWNERSHIP.get()
    if ownership is not None:
        ownership.revoked = True


def require_execution_ownership() -> None:
    ownership = ACTIVE_OWNERSHIP.get()
    if ownership is not None and ownership.revoked:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="scheduler.fence_rejected",
                category=ErrorCategory.CONFLICT,
                message="execution ownership was revoked; recover under a fresh lease",
                safe_to_resume=True,
            )
        )
