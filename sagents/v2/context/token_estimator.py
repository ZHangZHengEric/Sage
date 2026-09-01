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
