"""Window context reducer plugin."""

from __future__ import annotations

import hashlib
import json

from sagents.v2.context.contracts import ContextProjection
from sagents.v2.context.plugins.estimator_json import JsonHeuristicTokenEstimator
from sagents.v2.context.token_estimator import TokenEstimator
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
        self.estimator = estimator or JsonHeuristicTokenEstimator()

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
        systems = tuple(value for value in messages if value.role == "system")
        payload = tuple(value for value in messages if value.role != "system")
        units = self._units(payload)
        latest_user = next(
            (
                index
                for index in range(len(units) - 1, -1, -1)
                if any(message.role == "user" for message in units[index])
            ),
            None,
        )
        dropped = []

        def flattened():
            return (*systems, *(message for unit in units for message in unit))

        while self._over(flattened(), maximum, budget.max_messages):
            removable = next(
                (index for index in range(len(units)) if index != latest_user), None
            )
            if removable is None:
                raise self._error(
                    "context.budget_exhausted",
                    "protected system and latest-user context exceed the model budget",
                )
            dropped.extend(units.pop(removable))
            if latest_user is not None and removable < latest_user:
                latest_user -= 1
        retained = tuple(flattened())
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
            estimated_tokens=self.estimator.estimate(retained),
            source_message_count=len(messages),
            dropped_message_count=len(dropped),
            dropped_digest=digest,
            strategy="window" if dropped else "none",
        )

    def _over(self, messages, maximum, max_messages):
        return self.estimator.estimate(messages) > maximum or (
            max_messages is not None and len(messages) > max_messages
        )

    @staticmethod
    def _units(messages):
        units = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "assistant" and message.tool_calls:
                expected = {call.tool_call_id for call in message.tool_calls}
                unit = [message]
                index += 1
                while index < len(messages) and messages[index].role == "tool":
                    if messages[index].tool_call_id in expected:
                        unit.append(messages[index])
                    index += 1
                units.append(tuple(unit))
                continue
            units.append((message,))
            index += 1
        return units

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
