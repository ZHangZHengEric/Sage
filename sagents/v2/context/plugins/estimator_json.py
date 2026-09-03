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
            payload = message.model_dump(mode="json")
            media_tokens = 0
            for block in payload.get("content", ()):
                if not isinstance(block, dict) or block.get("kind") != "image":
                    continue
                media_tokens += 256 if block.get("detail") == "low" else 4_096
                uri = str(block.get("uri") or "")
                if uri.startswith("data:"):
                    header = uri.partition(",")[0]
                    block["uri"] = f"{header},<opaque-image-data>"
            encoded = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            total += (
                self.message_overhead
                + math.ceil(len(encoded) / self.bytes_per_token)
                + media_tokens
            )
        return total
