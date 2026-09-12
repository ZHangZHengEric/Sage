"""Token-estimation port and host-owned adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sagents.v2.model.contracts import ModelMessage


class TokenEstimator(Protocol):
    """Synchronous, side-effect-free estimator used on every projection pass."""

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int: ...


class CallableTokenEstimator:
    """Adapter for application-owned tokenizers without a Sage dependency."""

    def __init__(
        self,
        estimator_id: str,
        callback: Callable[[tuple[ModelMessage, ...]], int],
    ) -> None:
        self.estimator_id = estimator_id
        self.callback = callback

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        value = int(self.callback(messages))
        if value < 0:
            raise ValueError("token estimator cannot return a negative value")
        return value


async def estimate_tokens_async(estimator, messages):
    """Only built-ins opt into worker execution; custom ports keep their contract."""
    method = getattr(estimator, "estimate_async", None)
    if method is not None:
        return await method(messages)
    return estimator.estimate(messages)


class MessageTokenCounter:
    """Projection-local accounting; never assume a custom estimator is additive."""

    def __init__(self, estimator, costs):
        self.estimator = estimator
        self.costs = costs

    @classmethod
    async def create(cls, estimator, messages):
        method = getattr(estimator, "estimate_messages_async", None)
        if not getattr(estimator, "additive", False) or method is None:
            return cls(estimator, None)
        values = await method(messages)
        return cls(estimator, dict(zip(map(id, messages), values, strict=True)))

    def estimate(self, messages):
        if self.costs is None:
            return self.estimator.estimate(tuple(messages))
        total = 0
        for message in messages:
            key = id(message)
            # Only original messages are cached by identity. New temporary
            # messages must not survive here as IDs can be reused by Python.
            value = self.costs.get(key)
            total += self.estimator.estimate((message,)) if value is None else value
        return total
