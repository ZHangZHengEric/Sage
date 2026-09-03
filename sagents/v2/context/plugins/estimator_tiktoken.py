"""Official token-estimator plugin: optional OpenAI tiktoken encoding."""

from __future__ import annotations

import json
from typing import Any

from sagents.v2.model.contracts import ModelMessage


class TiktokenTokenEstimator:
    """Optional OpenAI tokenizer plugin with lazy dependency loading."""

    plugin_id = "sage.context.token-estimator.tiktoken"
    name = "Tiktoken token estimator"
    description = "Uses tiktoken encodings when the optional package is installed."
    estimator_id = "tiktoken"

    def __init__(
        self,
        *,
        model: str | None = None,
        encoding_name: str = "cl100k_base",
        encoder: Any | None = None,
        tokens_per_message: int = 6,
    ) -> None:
        if tokens_per_message < 0:
            raise ValueError("tokens_per_message cannot be negative")
        if encoder is None:
            try:
                import tiktoken
            except ImportError as exc:
                raise RuntimeError(
                    "tiktoken estimator requires the optional 'tiktoken' package"
                ) from exc
            if model is not None:
                try:
                    encoder = tiktoken.encoding_for_model(model)
                except KeyError:
                    encoder = tiktoken.get_encoding(encoding_name)
            else:
                encoder = tiktoken.get_encoding(encoding_name)
        self.encoder = encoder
        self.tokens_per_message = tokens_per_message

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
            total += self.tokens_per_message + media_tokens
            total += len(
                self.encoder.encode(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                )
            )
        return total
