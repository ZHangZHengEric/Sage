"""Official token-estimator plugin: CJK-aware character heuristic."""

from __future__ import annotations

import math
import unicodedata

from sagents.v2.context.estimation import CachedMessageEstimator


class UnicodeHeuristicTokenEstimator(CachedMessageEstimator):
    """Text-oriented estimate that treats CJK and symbol-heavy text conservatively."""

    plugin_id = "sage.context.token-estimator.unicode-heuristic"
    name = "Unicode heuristic token estimator"
    description = "Estimates tokens from Unicode code-point length."
    estimator_id = "unicode-heuristic"

    def __init__(
        self,
        *,
        ascii_chars_per_token: float = 4.0,
        non_ascii_chars_per_token: float = 1.5,
        message_overhead: int = 6,
    ) -> None:
        if ascii_chars_per_token <= 0 or non_ascii_chars_per_token <= 0:
            raise ValueError("characters-per-token values must be positive")
        if message_overhead < 0:
            raise ValueError("message_overhead cannot be negative")
        self.ascii_chars_per_token = ascii_chars_per_token
        self.non_ascii_chars_per_token = non_ascii_chars_per_token
        self.message_overhead = message_overhead
        self._init_cache()

    def _cache_identity(self):
        return (
            self.ascii_chars_per_token,
            self.non_ascii_chars_per_token,
            self.message_overhead,
        )

    def _text_tokens(self, value):
        ascii_count = 0
        non_ascii_weight = 0.0
        for character in value:
            if character.isascii():
                ascii_count += 1
            else:
                non_ascii_weight += (
                    1.25 if unicodedata.category(character).startswith("S") else 1.0
                )
        return (
            self.message_overhead
            + math.ceil(ascii_count / self.ascii_chars_per_token)
            + math.ceil(non_ascii_weight / self.non_ascii_chars_per_token)
        )
