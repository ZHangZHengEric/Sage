"""Request-scoped calibration from reported input usage, never per-item truth."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import math


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def message_fingerprints(messages) -> tuple[str, ...]:
    # Include image bytes and provider continuation state in identity. Redacting
    # these here would allow a different image to borrow a previous image's cost.
    return tuple(fingerprint(m.model_dump(mode="json")) for m in messages)


@dataclass(frozen=True)
class InputUsageBaseline:
    scope: str
    request_id: str
    messages: tuple[str, ...]
    input_tokens: int
    non_message_tokens: int

    def matches(self, messages) -> bool:
        return (
            len(messages) >= len(self.messages)
            and message_fingerprints(messages[: len(self.messages)]) == self.messages
        )

    @property
    def margin(self) -> int:
        return max(128, math.ceil(self.input_tokens * 0.03))


_active: ContextVar[InputUsageBaseline | None] = ContextVar(
    "sage_v2_input_usage_baseline",
    default=None,
)


@contextmanager
def input_usage_scope(baseline):
    token = _active.set(baseline)
    try:
        yield
    finally:
        _active.reset(token)


class CalibratedEstimator:
    """Non-additive: only the complete unchanged prefix has reported usage."""

    additive = False

    def __init__(self, estimator, baseline):
        self.estimator = estimator
        self.baseline = baseline

    def estimate(self, messages):
        baseline = self.baseline
        if not baseline.matches(messages):
            return self.estimator.estimate(messages)
        return (
            baseline.input_tokens
            - baseline.non_message_tokens
            + baseline.margin
            + self.estimator.estimate(messages[len(baseline.messages) :])
        )

    async def estimate_async(self, messages):
        baseline = self.baseline
        matched = baseline.matches(messages)
        suffix = messages[len(baseline.messages) :] if matched else messages
        method = getattr(self.estimator, "estimate_async", None)
        count = await method(suffix) if method else self.estimator.estimate(suffix)
        if not matched:
            return count
        return (
            baseline.input_tokens
            - baseline.non_message_tokens
            + baseline.margin
            + count
        )


def scoped_estimator(estimator):
    baseline = _active.get()
    if baseline is None or not getattr(estimator, "additive", False):
        return estimator
    return CalibratedEstimator(estimator, baseline)
