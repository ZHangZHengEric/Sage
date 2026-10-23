"""Opt-in local retries and a parallel pool that retains successful siblings."""

import asyncio

from sagents.v2.optimization.recovery import (
    OptimizationRecoveryRequired,
    OptimizationTransientFailure,
)


class TargetCallFailure(RuntimeError):
    """A failed invocation in a host-attested disposable target environment."""

    def __init__(self, original):
        self.original = original
        super().__init__(type(original).__name__)


async def retry_delay(attempt):
    await asyncio.sleep(min(60, 2 ** min(attempt, 6)))


def retry_allowed(error):
    original = error.original if isinstance(error, TargetCallFailure) else error
    metadata = getattr(original, "rsi_failure_metadata", {})
    if (
        metadata.get("phase") == "execution"
        and metadata.get("state") in {"suspended", "failed"}
        and not metadata.get("error_type")
        and not metadata.get("retryable")
    ):
        return False
    if metadata.get("error_type") == "PermissionError":
        return False
    if isinstance(original, (PermissionError, OptimizationRecoveryRequired)):
        return False
    if getattr(original, "rsi_requires_feedback", False):
        return False
    if getattr(original, "rsi_local_retries_exhausted", False):
        return False
    if any(
        marker in str(original).lower()
        for marker in (
            "frozen scorer source changed",
            "configuration differs",
            "binding differs",
            "engine differs",
            "outside rsi host grant",
            "tools exceed",
        )
    ):
        return False
    return True


async def retry_call(
    invoke, *, retries=0, on_retry=None, before_retry=None, only=(Exception,)
):
    for attempt in range(max(retries, 12) + 1 if retries else 1):
        try:
            return await invoke()
        except only as error:
            if not retries or not retry_allowed(error):
                raise
            original = error.original if isinstance(error, TargetCallFailure) else error
            limit = (
                12 if isinstance(original, OptimizationTransientFailure) else retries
            )
            if attempt >= limit:
                error.rsi_local_retries_exhausted = True
                raise
            if on_retry is not None:
                original = (
                    error.original if isinstance(error, TargetCallFailure) else error
                )
                on_retry(attempt + 1, original)
            if before_retry is not None:
                await before_retry()
            await retry_delay(attempt + 1)


async def settle_cases(cases, evaluate, *, max_concurrency, on_error=None):
    """Failures become results until ALL siblings drain; cancellation stays immediate."""
    slots = asyncio.Semaphore(max_concurrency)

    async def bounded(case):
        async with slots:
            try:
                return await evaluate(case)
            except Exception as error:
                if on_error is not None:
                    on_error(case, error)
                return error

    tasks = []
    async with asyncio.TaskGroup() as group:
        for case in cases:
            tasks.append(group.create_task(bounded(case)))
    values = [task.result() for task in tasks]
    errors = [value for value in values if isinstance(value, Exception)]
    if errors:
        error = (
            errors[0]
            if len(errors) == 1
            else ExceptionGroup(
                "Isolated RSI calls failed after all cases drained", errors
            )
        )
        error.rsi_siblings_drained = True
        if all(getattr(item, "rsi_local_retries_exhausted", False) for item in errors):
            error.rsi_local_retries_exhausted = True
        raise error
    return values
