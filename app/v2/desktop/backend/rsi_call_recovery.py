"""Bounded checkpoint recovery for failures inside isolated RSI calls."""

import asyncio
import json

from sagents.v2.optimization.recovery import (
    OptimizationRecoveryRequired,
    OptimizationTransientFailure,
)


def failed_call(error, journal):
    """Return public retry metadata, never provider messages or task contents.

    The Desktop runner already grants disposable target environments and private
    editor/evaluation workspaces. Recovery must still pass the SDK journal and
    binding checks; this function cannot authorize replay of an external effect.
    """
    if getattr(error, "rsi_siblings_drained", False):
        return None
    if getattr(error, "rsi_local_retries_exhausted", False):
        return None
    if isinstance(error, (asyncio.CancelledError, PermissionError, OptimizationRecoveryRequired)):
        return None
    # Integrity/configuration failures are not failed inference attempts.
    if isinstance(error, (ValueError, RuntimeError)) and any(
        marker in str(error).lower()
        for marker in ("frozen scorer source changed", "configuration differs", "binding differs",
                       "engine differs", "outside rsi host grant", "tools exceed")
    ):
        return None
    pending, last = {}, None
    try:
        with journal.open() as stream:
            for line in stream:
                event = json.loads(line)
                name, data = event["event"], event.get("data", {})
                if name in {"test_generation_started", "training_generation_started", "final_test_generation_started"}:
                    last = {"role": "test_design", "round": data.get("round", 0),
                            "trial": 1, "case_id": None, "phase": data.get("split", "training")}
                elif name in {"target_call_started", "agent_call_started", "scoring_call_started"}:
                    row = {key: data.get(key) for key in ("role", "round", "trial", "case_id", "phase")}
                    row["role"] = row["role"] or ("scoring" if name.startswith("scoring") else "execution")
                    pending[data["call_id"]] = row
                    last = row
                elif name in {"target_call_completed", "agent_call_completed", "scoring_call_completed"}:
                    last = pending.pop(data["call_id"], last)
                elif name == "scoring_call_failed":
                    last = pending.pop(data["call_id"], last)
    except (OSError, ValueError, KeyError):
        return None
    if last is None:
        return None
    # Oldest unfinished call is the one whose deadline expires first. Concurrent
    # siblings may have emitted newer events before cancellation reaches them.
    row = next(iter(pending.values()), last) if isinstance(error, TimeoutError) else last
    return {**row, "error_type": type(error).__name__,
            "retry_limit": 12 if isinstance(error, OptimizationTransientFailure) else 3}
