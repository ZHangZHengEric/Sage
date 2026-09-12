"""Official token-estimator plugin: conservative JSON wire-size heuristic."""

from __future__ import annotations

import math

from sagents.v2.context.estimation import CachedMessageEstimator


class JsonHeuristicTokenEstimator(CachedMessageEstimator):
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
        self._init_cache()

    def _cache_identity(self):
        return (self.bytes_per_token, self.message_overhead)

    def _text_tokens(self, value):
        return self.message_overhead + math.ceil(
            len(value.encode("utf-8")) / self.bytes_per_token
        )
