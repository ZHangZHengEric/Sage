"""Official token-estimator plugin: conservative JSON wire-size heuristic."""

from __future__ import annotations

import json
import math

from sagents.v2.model.contracts import ModelMessage


class JsonHeuristicTokenEstimator:
    """Conservative provider-neutral estimate of the complete wire structure."""

    plugin_id = "sage.context.token-estimator.json-heuristic"
    name = "JSON heuristic token estimator"
    description = "Estimates tokens from JSON-serialized message size."
    estimator_id = "json-heuristic"

    def __init__(self, *, bytes_per_token: float = 4.0, message_overhead: int = 6):
        if bytes_per_token <= 0:
            raise ValueError("bytes_per_token must be positive")
        if message_overhead < 0:
            raise ValueError("message_overhead cannot be negative")
        self.bytes_per_token = bytes_per_token
        self.message_overhead = message_overhead

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        total = 0
        for message in messages:
            encoded = json.dumps(
                message.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            total += self.message_overhead + math.ceil(
                len(encoded) / self.bytes_per_token
            )
        return total

