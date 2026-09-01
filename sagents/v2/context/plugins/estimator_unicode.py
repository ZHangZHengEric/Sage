"""Official token-estimator plugin: CJK-aware character heuristic."""

from __future__ import annotations

import json
import math
import unicodedata

from sagents.v2.model.contracts import ModelMessage


class UnicodeHeuristicTokenEstimator:
    """Text-oriented estimate that treats CJK and symbol-heavy text conservatively."""

    plugin_id = "sage.context.token-estimator.unicode-heuristic"
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
        self.ascii_chars_per_token = ascii_chars_per_token
        self.non_ascii_chars_per_token = non_ascii_chars_per_token
        self.message_overhead = message_overhead

    def estimate(self, messages: tuple[ModelMessage, ...]) -> int:
        total = 0
        for message in messages:
            value = json.dumps(
                message.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            ascii_count = 0
            non_ascii_weight = 0.0
            for character in value:
                if character.isascii():
                    ascii_count += 1
                    continue
                category = unicodedata.category(character)
                non_ascii_weight += 1.25 if category.startswith("S") else 1.0
            total += self.message_overhead
            total += math.ceil(ascii_count / self.ascii_chars_per_token)
            total += math.ceil(non_ascii_weight / self.non_ascii_chars_per_token)
        return total
