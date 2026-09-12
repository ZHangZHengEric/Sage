"""Window context reducer plugin."""

from __future__ import annotations

import hashlib
import json

from sagents.v2.context.contracts import ContextProjection
from sagents.v2.context.token_estimator import TokenEstimator, MessageTokenCounter
from sagents.v2.context.estimation import WireSizeTokenEstimator
from sagents.v2.context.partition import conversation_units, current_turn_boundary
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)


class WindowContextReducer:
    """Drops oldest complete conversation units while preserving tool pairs."""

    plugin_id = "sage.context.reducer.window"
    name = "Window context reducer"
    description = "Drops oldest units to keep the prompt inside a token window."

    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        self.estimator = estimator or WireSizeTokenEstimator()

    async def reduce(self, messages, budget, *, scope=None):
        maximum = (
            budget.max_input_tokens
            - budget.reserve_output_tokens
            - budget.reserve_input_tokens
        )
        if maximum <= 0:
            raise self._error(
                "context.invalid_budget",
                "output and final-request reserves consume the input budget",
            )
        systems = tuple(
            value for value in messages if value.role in {"system", "developer"}
        )
        payload = tuple(
            value for value in messages if value.role not in {"system", "developer"}
        )
        units = self._units(payload)
        counter = await MessageTokenCounter.create(self.estimator, messages)
        system_tokens = counter.estimate(systems)
        if system_tokens > budget.max_system_tokens:
            raise self._error(
                "context.system_budget_exhausted",
                "system instructions exceed their token budget",
            )
        boundary = current_turn_boundary(units)
        costs = [counter.estimate(unit) for unit in units]
        total = system_tokens + sum(costs)
        count = len(systems) + sum(map(len, units))
        start = 0

        def flattened():
            return (*systems, *(message for unit in units[start:] for message in unit))

        def over():
            tokens = (
                total if counter.costs is not None else counter.estimate(flattened())
            )
            return tokens > maximum or (
                budget.max_messages is not None and count > budget.max_messages
            )

        while over():
            if start >= boundary:
                raise self._error(
                    "context.budget_exhausted",
                    "system and current user turn exceed the model budget",
                )
            total -= costs[start]
            count -= len(units[start])
            start += 1
        retained = tuple(flattened())
        dropped = tuple(message for unit in units[:start] for message in unit)
        digest = None
        if dropped:
            encoded = json.dumps(
                [value.model_dump(mode="json") for value in dropped],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        return ContextProjection(
            messages=retained,
            historical_messages=tuple(dropped),
            estimated_tokens=counter.estimate(retained),
            source_message_count=len(messages),
            dropped_message_count=len(dropped),
            dropped_digest=digest,
            strategy="window" if dropped else "none",
        )

    _units = staticmethod(conversation_units)

    @staticmethod
    def _error(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )
